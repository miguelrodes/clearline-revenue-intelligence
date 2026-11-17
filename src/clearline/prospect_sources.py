"""Bounded HTTPS retrieval for official directories, facility pages and manufacturer evidence."""
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit
import httpx2 as httpx

from .prospect_agent import normalized_url
from .store import utcnow

DIRECTORIES = {
    'WY': 'https://corrections.wyo.gov/facilities',
    'CA': 'https://www.cdcr.ca.gov/facility-locator/',
}
PROCUREMENT = {
    'WY': 'https://ai.wyo.gov/divisions/general-services/purchasing',
    'CA': 'https://www.cdcr.ca.gov/contracts/',
}


def valid_url(raw, vendor=False):
    try:
        parsed = urlsplit(normalized_url(raw))
        if parsed.hostname.endswith('.gov') or (vendor and parsed.hostname == 'swabtek.com'):
            return raw.split('#')[0]
    except (AttributeError, TypeError, ValueError):
        pass
    raise ValueError('Use a public HTTPS US government directory or an approved manufacturer source.')


class PublicPage(HTMLParser):
    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url, self.text, self.title, self.links = url, [], [], []
        self.omit, self.in_title, self.href, self.label = 0, False, None, []

    def handle_starttag(self, tag, attrs):
        if tag in ('script','style','noscript','svg'):
            self.omit += 1
        if self.omit:
            return
        if tag == 'title':
            self.in_title = True
        if tag == 'a':
            self.href = dict(attrs).get('href')
            self.label = []

    def handle_data(self, text):
        if self.omit:
            return
        text = ' '.join(text.split())
        if not text:
            return
        self.text.append(text)
        if self.in_title:
            self.title.append(text)
        if self.href:
            self.label.append(text)

    def handle_endtag(self, tag):
        if tag in ('script','style','noscript','svg'):
            self.omit = max(0,self.omit-1)
        if self.omit:
            return
        if tag == 'title':
            self.in_title = False
        if tag == 'a' and self.href:
            if self.label and not self.href.startswith('#'):
                try:
                    url = valid_url(urljoin(self.url,self.href), True)
                    link = {'label':' '.join(self.label),'url':url}
                    if link not in self.links:
                        self.links.append(link)
                except ValueError:
                    pass
            self.href, self.label = None, []

    def result(self):
        return {'url':self.url,'title':' '.join(self.title),'text':' '.join(self.text),
                'links':self.links,'blocks':self.text,'retrieved_at':utcnow()}


async def fetch_page(url, vendor=False):
    url = valid_url(url,vendor)
    async with httpx.AsyncClient(timeout=httpx.Timeout(10,connect=5),follow_redirects=False,
                                 headers={'User-Agent':'Clearline-Revenue-Research/1.0 (+public institutional directory review)'}) as client:
        for _ in range(4):
            async with client.stream('GET',url) as response:
                if response.is_redirect:
                    url = valid_url(urljoin(url,response.headers['location']),vendor)
                    continue
                response.raise_for_status()
                if 'html' not in response.headers.get('content-type',''):
                    raise ValueError('Only public HTML pages are supported for this bounded search.')
                buf = bytearray()
                async for block in response.aiter_bytes():
                    if len(buf)+len(block) > 2_000_000:
                        raise ValueError('Official page exceeds the bounded HTML retrieval limit.')
                    buf.extend(block)
                doc = PublicPage(url)
                doc.feed(buf.decode(response.encoding or 'utf-8', errors='replace'))
                return doc.result()
    raise ValueError('Too many redirects while reading the public source.')


def excerpt(page, length=4800):
    # Manufacturer navigation and catalogs precede product use/limitations. Include
    # factual neighborhoods in addition to the page opening, always with original context.
    text = page['text']
    snippets = [text[:length//2]]
    for phrase in ('presumptive','capacity','about the facility','about purchasing','authorized distributor',
                   'how it works','security level','mail policy','operational capacity','narcotics test'):
        found = re.search(re.escape(phrase),text,re.I)
        if found:
            start=max(0,found.start()-140)
            quote=text[start:start+600]
            if quote not in snippets[0]:
                snippets.append(quote)
    if len(' '.join(snippets)) < length:
        snippets.append(text[len(snippets[0]):length])
    return ' […] '.join(snippets)[:length]
