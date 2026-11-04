#!/usr/bin/env python3
"""Source accessibility / quotation check. NOT automatic fact checking.

Explicit --allow-network opt-in, no credentials/cookies, no proxy, limit downloads,
reject obvious private/internal addresses. Run against PUBLIC links only. DNS changes,
misleading text, paywalls and PDF claims still require independent human judgment.
"""
from __future__ import annotations
import argparse
import codecs
import http.client
from collections import Counter, defaultdict
import datetime as dt
from html.parser import HTMLParser
import hashlib
import ipaddress
import json
import re
import socket
import ssl
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from gf_common import VERSION, atomic_write_json, old_entry

MAX_BYTES = 2_000_000
TIMEOUT = 8
COMMON = set('a an the and or for to in of on with by from is are at as be has have that this will can than which their its was were'.split())


class Scraper(HTMLParser):
    def __init__(self):
        super().__init__(); self.skip=0; self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript','svg'): self.skip+=1
    def handle_endtag(self,tag):
        if tag in ('script','style','noscript','svg') and self.skip: self.skip-=1
    def handle_data(self,data):
        if not self.skip:self.parts.append(data)


class PinnedHTTPConnection(http.client.HTTPConnection):
    """Connects only to the vetted IP; the Host header keeps the original name."""
    def __init__(self,host,port,vetted_ips,connector=None,**kw):
        super().__init__(host,port,**kw); self.vetted_ips=list(vetted_ips); self.connector=connector or socket.create_connection
    def _open(self):
        err=None
        for ip in self.vetted_ips[:3]:  # next vetted address if the first is down
            try:return self.connector((ip,self.port),self.timeout)
            except OSError as exc:err=exc
        raise err or OSError('no address')
    def connect(self):
        self.sock=self._open()


class PinnedHTTPSConnection(PinnedHTTPConnection):
    def __init__(self,host,port,vetted_ips,connector=None,context=None,**kw):
        super().__init__(host,port,vetted_ips,connector,**kw); self.context=context or ssl.create_default_context()
    def connect(self):
        sock=self._open()
        try:self.sock=self.context.wrap_socket(sock,server_hostname=self.host)
        except BaseException:
            sock.close();raise


def _vet(url, resolver=None):
    value=urlsplit(url)
    if value.scheme not in ('https','http') or not value.hostname or value.username or value.password:
        raise ValueError('Only public HTTP(S) URLs without credentials are supported')
    hostname=value.hostname
    if hostname.lower() in {'localhost','localhost.localdomain'} or hostname.endswith(('.localhost','.local','.internal','.test')):
        raise ValueError('Local/private hostname blocked')
    port=value.port or (443 if value.scheme=='https' else 80)
    if port!=(443 if value.scheme=='https' else 80):
        raise ValueError(f'Port {port} not allowed; only 80 and 443 are fetched')
    try:hostname=hostname.encode('idna').decode('ascii')
    except UnicodeError as exc:raise ValueError('Invalid hostname') from exc
    resolver=resolver or socket.getaddrinfo
    try:
        addrs=resolver(hostname,port,type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError('Could not resolve host') from exc
    if not addrs:
        raise ValueError('Host did not resolve')
    ips=[]
    for addr in addrs:
        ip=ipaddress.ip_address(addr[4][0].split('%')[0])
        if not ip.is_global:
            raise ValueError('Nonpublic network target blocked')
        if str(ip) not in ips:ips.append(str(ip))
    return hostname.lower(),port,value.scheme,ips


def check_public_url(url, resolver=None):
    """Vet once; callers connect to the returned IP, never re-resolve."""
    host,port,scheme,ips=_vet(url,resolver)
    return host,port,scheme,ips[0]


def fetch_public(url, resolver=None, connector=None, context=None):
    current=url; downgraded=False
    for _ in range(5):
        host,port,scheme,ips=_vet(current,resolver)
        parts=urlsplit(current)
        hosthdr=f'[{host}]' if ':' in host else host
        if port!=(443 if scheme=='https' else 80):hosthdr+=f':{port}'
        path=(parts.path or '/')+('?'+parts.query if parts.query else '')
        headers={'Host':hosthdr,'User-Agent':'Greenfield-Evidence-Inspector/2.0 (+manual-review-required)','Accept':'text/html,text/plain;q=0.9,application/pdf;q=0.5','Accept-Encoding':'identity','Connection':'close'}
        conn=(PinnedHTTPSConnection(host,port,ips,connector,context,timeout=TIMEOUT) if scheme=='https'
              else PinnedHTTPConnection(host,port,ips,connector,timeout=TIMEOUT))
        try:
            try:
                conn.request('GET',path,headers=headers); response=conn.getresponse()
            except (http.client.HTTPException, TimeoutError, OSError) as err:
                raise RuntimeError('Connection failed or timed out') from err
            if response.status in (301,302,303,307,308) and response.getheader('Location'):
                nxt=urljoin(current,response.getheader('Location'))
                downgraded|= scheme=='https' and urlsplit(nxt).scheme=='http'
                current=nxt
                continue
            if response.status>=400 or response.status<200:
                raise RuntimeError(f'HTTP {response.status}')
            mime=response.msg.get_content_type()
            if mime not in ('text/html','text/plain'):
                raise RuntimeError(f'Unsupported document type ({mime}); review manually')
            if response.getheader('Content-Encoding','identity').lower() not in ('','identity'):
                raise RuntimeError('Unsupported content encoding; review manually')
            try:blob=response.read(MAX_BYTES+1)
            except (http.client.HTTPException, TimeoutError, OSError) as err:
                raise RuntimeError('Connection failed or timed out') from err
            if len(blob)>MAX_BYTES:
                raise RuntimeError('Document exceeds 2 MB limit')
            charset=response.msg.get_content_charset() or 'utf-8'; fallback=False
            try:codecs.lookup(charset)
            except LookupError:charset='utf-8';fallback=True
            raw=blob.decode(charset,errors='replace')
            if mime=='text/html':
                parser=Scraper();parser.feed(raw);raw=' '.join(parser.parts)
            text=' '.join(raw.split())
            out={'url':current,'content_sha256':hashlib.sha256(blob).hexdigest(),'text':text,'bytes':len(blob),'mime':mime}
            if fallback:out['charset_fallback']=True
            if downgraded:out['downgraded_to_http']=True
            return out
        finally:conn.close()
    raise RuntimeError('Too many redirects')


def normal(text):
    return ' '.join(re.findall(r'[\w]+',str(text).casefold()))


def analyze(data, *, allow_network=False, fetcher=None, as_of=None, stale_days=730):
    claims=data.get('claims',[])
    date=dt.date.fromisoformat(as_of) if as_of else dt.date.today()
    findings=[];cache={}; origins=defaultdict(list)
    for claim in claims:
        url=claim.get('source_url','')
        if not url: continue
        split=urlsplit(url)
        # These are heuristics; two URLs on a publisher may still be independent studies.
        origin=str(claim.get('independent_origin') or split.hostname or '').lower()
        origins[origin].append(claim.get('id',''))
        issue=[]
        published=claim.get('published_date')
        if published:
            try:
                if (date-dt.date.fromisoformat(published)).days > stale_days:issue.append('published_older_than_freshness_window')
                if dt.date.fromisoformat(published)>date: issue.append('publication_in_future')
            except (ValueError,TypeError):issue.append('invalid_publication_date')
        item={'claim_id':claim.get('id'),'source_url':url,'origin':origin,'published_date':published or None,
              'fetched_at':None,'fetch_status':'not_fetched','excerpt_check':'not_checked','overlap_ratio':None,'issues':issue}
        if allow_network:
            try:
                if url not in cache:cache[url]=(fetcher or fetch_public)(url)
                page=cache[url];item['source_url_final']=page['url'];item['content_sha256']=page['content_sha256'];item['fetched_at']=dt.datetime.now(dt.timezone.utc).isoformat();item['fetch_status']='fetched'
                if page.get('charset_fallback'):item['charset_fallback']=True
                if page.get('downgraded_to_http'):issue.append('downgraded_to_http')
                quote=claim.get('supporting_quote','')
                if quote:
                    item['excerpt_check']='found' if normal(quote) in normal(page['text']) else 'not_found'
                    if item['excerpt_check']=='not_found':issue.append('quoted_passage_not_found')
                else:
                    item['excerpt_check']='no_quote_supplied'
                terms={x for x in normal(claim.get('statement','')).split() if len(x)>3 and x not in COMMON}
                page_words=set(normal(page['text'][:300_000]).split())
                item['overlap_ratio']=round(len(terms & page_words)/len(terms),2) if terms else None
                # Lexical overlap is a retrieval hint, not semantic proof.
            except Exception as err:  # one bad source must not abort the report
                item['fetch_status']='failed';item['issues'].append(str(err)[:130] or type(err).__name__)
        findings.append(item)
    for item in findings:
        if len(origins[item['origin']])>1:
            item['issues'].append('shared_reported_origin_check_independence')
        if not item['origin']:item['issues'].append('unknown_origin')
    return {'schema_version':'2.0','as_of':date.isoformat(),'automated_verification_of_truth':False,
            'network_used':bool(allow_network),'claims':findings,
            'summary':{'total_sources':len(findings),'fetched':sum(x['fetch_status']=='fetched' for x in findings),
                       'missing_quotes':sum(x['excerpt_check']=='not_found' for x in findings),
                       'fetch_failures':sum(x['fetch_status']=='failed' for x in findings),
                       'shared_origin_groups':sum(len(v)>1 for v in origins.values())},
            'limitations':'Source text and matching excerpts do not establish claim truth. Screenshots, PDFs, JS pages, paywalls, semantics and behavioral receipts need human review.'}


def check(evaluation,output,allow_network=False,stale_days=730):
    """Check the evaluation's sources, write the full report to output, return its summary."""
    data=json.loads(Path(evaluation).read_text(encoding='utf-8'))
    if stale_days<1:raise ValueError('stale-days must be positive')
    report=analyze(data,allow_network=allow_network,as_of=data.get('as_of'),stale_days=stale_days)
    output=Path(output);output.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    atomic_write_json(output,report,mode=0o600)
    return report['summary']


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version',action='version',version=f'%(prog)s {VERSION}')
    p.add_argument('evaluation',type=Path)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--allow-network',action='store_true',help='Explicitly fetch PUBLIC pages; disabled by default')
    p.add_argument('--stale-days',type=int,default=730)
    args=p.parse_args(argv)
    try:
        print(json.dumps(check(args.evaluation,args.output,args.allow_network,args.stale_days),indent=2))
    except (OSError,ValueError,json.JSONDecodeError) as exc:
        print('ERROR:',exc,file=sys.stderr);return 2
    return 0

if __name__=='__main__':raise SystemExit(old_entry(main,'gf_evidence.py','greenfield sources check'))
