#!/usr/bin/env python3
"""Source accessibility / quotation check. NOT automatic fact checking.

Explicit --allow-network opt-in, no credentials/cookies, no proxy, limit downloads,
reject obvious private/internal addresses. Run against PUBLIC links only. DNS changes,
misleading text, paywalls and PDF claims still require independent human judgment.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import datetime as dt
from html.parser import HTMLParser
import hashlib
import ipaddress
import json
import re
import socket
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, ProxyHandler, Request
from urllib.error import HTTPError, URLError

from gf_common import VERSION

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


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


def check_public_url(url, resolver=None):
    value=urlsplit(url)
    if value.scheme not in ('https','http') or not value.hostname or value.username or value.password:
        raise ValueError('Only public HTTP(S) URLs without credentials are supported')
    hostname=value.hostname
    if hostname.lower() in {'localhost','localhost.localdomain'} or hostname.endswith(('.localhost','.local','.internal','.test')):
        raise ValueError('Local/private hostname blocked')
    # Resolve and inspect every address; this lowers SSRF risk but is not an
    # airtight DNS-rebinding defense. Never grant this script internal access.
    resolver=resolver or socket.getaddrinfo
    try:
        addrs=resolver(hostname,value.port or (443 if value.scheme=='https' else 80),type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError('Could not resolve host') from exc
    if not addrs:
        raise ValueError('Host did not resolve')
    for addr in addrs:
        ip=ipaddress.ip_address(addr[4][0])
        if not ip.is_global:
            raise ValueError('Nonpublic network target blocked')
    return hostname.lower()


def fetch_public(url):
    opener=build_opener(ProxyHandler({}),NoRedirect())
    current=url
    for _ in range(4):
        check_public_url(current)
        req=Request(current,headers={'User-Agent':'Greenfield-Evidence-Inspector/2.0 (+manual-review-required)','Accept':'text/html,text/plain;q=0.9,application/pdf;q=0.5'})
        try:
            response=opener.open(req,timeout=TIMEOUT)
        except HTTPError as err:
            if err.code in (301,302,303,307,308) and err.headers.get('Location'):
                current=urljoin(current,err.headers['Location'])
                continue
            raise RuntimeError(f'HTTP {err.code}') from err
        except (URLError, TimeoutError, OSError) as err:
            raise RuntimeError('Connection failed or timed out') from err
        with response:
            mime=response.headers.get_content_type()
            if mime not in ('text/html','text/plain'):
                raise RuntimeError(f'Unsupported document type ({mime}); review manually')
            blob=response.read(MAX_BYTES+1)
            if len(blob)>MAX_BYTES:
                raise RuntimeError('Document exceeds 2 MB limit')
            charset=response.headers.get_content_charset() or 'utf-8'
            raw=blob.decode(charset,errors='replace')
            if mime=='text/html':
                parser=Scraper();parser.feed(raw);raw=' '.join(parser.parts)
            text=' '.join(raw.split())
            return {'url':current,'content_sha256':hashlib.sha256(blob).hexdigest(),'text':text,'bytes':len(blob),'mime':mime}
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
            except (ValueError,RuntimeError) as err:
                item['fetch_status']='failed';item['issues'].append(str(err)[:130])
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


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version',action='version',version=f'%(prog)s {VERSION}')
    p.add_argument('evaluation',type=Path)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--allow-network',action='store_true',help='Explicitly fetch PUBLIC pages; disabled by default')
    p.add_argument('--stale-days',type=int,default=730)
    args=p.parse_args(argv)
    try:
        data=json.loads(args.evaluation.read_text(encoding='utf-8'))
        if args.stale_days<1:raise ValueError('stale-days must be positive')
        report=analyze(data,allow_network=args.allow_network,as_of=data.get('as_of'),stale_days=args.stale_days)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report['summary'],indent=2))
    except (OSError,ValueError,json.JSONDecodeError) as exc:
        print('ERROR:',exc,file=sys.stderr);return 2
    return 0

if __name__=='__main__':raise SystemExit(main())
