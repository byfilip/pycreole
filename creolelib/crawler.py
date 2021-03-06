# The Creole Crawler

import sys
import re
import os.path
import time
import robotparser
import bz2
import urllib2
import urlnorm
import mimetools
from cStringIO import StringIO
from elementtidy import TidyHTMLTreeBuilder
from base64 import urlsafe_b64encode, urlsafe_b64decode
from urlparse import urlsplit, urlunsplit, urljoin
from urllib import addinfourl

__author__ = "Filip Salomonsson"
__version__ = "0.1a"

XHTML_NS = "{http://www.w3.org/1999/xhtml}"

class DebugWriter:
    def __init__(self):
        self.file = sys.stderr
    def write(self, msg):
        self.file.write(msg)
    def __call__(self, msg):
        self.file.write(msg)
debug = DebugWriter()
    
def clean_url(url):
    (proto, host, path, params, frag) = urlsplit(urlnorm.norms(url))
    return urlunsplit((proto, host, path, params, ''))

class CrawlerException(Exception): pass
class WrongContentTypeException(CrawlerException): pass
class RobotsNotAllowedException(CrawlerException): pass
class WrongDomainException(CrawlerException): pass

class Crawler:
    """Web crawler."""

    USER_AGENT = "Creole/%s" % __version__
    robotparser.URLopener.version =  USER_AGENT
    
    def __init__(self, store=".store", throttle_delay=1):
        self.store = store
        self.throttle_delay = throttle_delay
        self.history = set()
        self.robotcache = {}
        self.lastvisit = {}

    def crawl(self, base_url):
        """Start a crawl from the given base URL."""
        # Reset the queue
        self.url_queue = [base_url]

        while len(self.url_queue) > 0:
            url = self.url_queue.pop()
            try:
                doc = self.retrieve(url)
                urls = self.extract_urls(doc, doc.geturl())
                self.url_queue.extend(urls)
                if len(urls) > 0:
                    print >> debug, "..Added %s new urls to queue." % len(urls)
            except RobotsNotAllowedException:
                print >> debug, "..I'm not allowed there."
            except WrongContentTypeException:
                print >> debug, "..Wrong content-type."
            except WrongDomainException:
                print >> debug, "..Wrong domain."
            except urllib2.HTTPError, e:
                print >> debug, "..HTTP Error %s" % e.code

    def retrieve(self, url):
        """Retrieve a single URL."""
        
        # Clean up the URL (normalize it and get rid of any
        # fragment identifier)        
        url = clean_url(url)
        (proto, host, path, params, _) = urlsplit(url)
        print >> debug, "Retrieving %s" % url

        # We use the path including parameters as an identifier
        path = urlunsplit(('', '', path, params, ''))

        store_dir = os.path.join(self.store, host)
        # Create store directory if it doesn't already exist.
        if not os.access(store_dir, os.F_OK):
            os.makedirs(store_dir)

        basename = urlsafe_b64encode(path)[:240]

        try:
            # Use cached robots.txt...
            rp = self.robotcache[host]
        except KeyError:
            # ...fetch and parse it if it wasn't in the cache
            rp = robotparser.RobotFileParser()
            rp.set_url(urljoin(url, "/robots.txt"))
            print >> debug, "Fetching /robots.txt first."
            rp.read()
            self.robotcache[host] = rp

        # Fetch the requested URL, if allowed (and not already fetched)
        if not rp.can_fetch(self.USER_AGENT, url):
            raise RobotsNotAllowedException

        # First, try in the store
        filename = os.path.join(store_dir, basename + ".bzip2")
        try:
            stored = bz2.BZ2File(filename)
            print >> debug, "..Already in store!"
            self.history.add(url)
            headers = mimetools.Message(
                open(os.path.join(store_dir, basename + ".headers")))
            return addinfourl(stored, headers, url)
        except IOError:
            pass

        # Customize the user-agent header
        headers = {"User-Agent": self.USER_AGENT}

        # Set up the request
        request = urllib2.Request(url, headers=headers)

        # Honor the throttling delay
        delta = time.time() - self.lastvisit.get(host, 0)
        if delta < self.throttle_delay:
            print >> debug, "Going too fast; sleeping for %.1f seconds..." \
                  % (self.throttle_delay - delta) 
            time.sleep(self.throttle_delay - delta)

        # Set lastvisit now, since urlopen might raise an exception
        self.lastvisit[host] = time.time()
        response = urllib2.urlopen(request)

        # Add original final url to history
        self.history.add(url)

        final_url = clean_url(response.geturl())

        # Check if the final URL is still within the same domain.
        # Barf if not.
        if not urlsplit(url)[:2] == urlsplit(final_url)[:2]:
            raise WrongDomainException
        
        # Add final URL to history
        self.history.add(final_url)

        info = response.info()
        content_type = info.get("content-type", "text/plain").split()[0]
        if not content_type.startswith("text/"):
            raise WrongContentTypeException("Won't fetch %s." % content_type)

        doc = StringIO(response.read())

        # It's the final path that's interesting now..
        (proto, host, path, params, _) = urlsplit(final_url)
        path = urlunsplit(('', '', path, params, ''))
        basename = urlsafe_b64encode(path)[:240]

        # Store the response
        filename = os.path.join(store_dir, basename)
        tmp_filename = filename + ".tmp"
        f = bz2.BZ2File(tmp_filename, 'w')
        f.write(doc.read())
        f.close()
        os.rename(tmp_filename, filename + '.bzip2')

        # ..and headers...
        filename = filename + ".headers"
        tmp_filename = filename + "'.tmp"
        f = open(tmp_filename, 'w')
        for (key, value) in sorted(response.info().items()):
            f.write("%s: %s\n" % (key, value))
        f.close()
        os.rename(tmp_filename, filename)

        print >> debug, "..Successfully stored!"

        doc.seek(0)
        return addinfourl(doc, response.info(), final_url)

    def extract_urls(self, doc, base_url):
        """Parses a document and returns URLS found in it."""
        try:
            tree = TidyHTMLTreeBuilder.parse(doc)
        except Exception, e:
            print >> debug, "..Error while parsing: %r" % e
            return set()
        root = tree.getroot()

        base_url = clean_url(base_url)

        urls = set()
        for elem in root.findall(".//%sa" % XHTML_NS):
            href = elem.get("href")
            if href is not None:
                href = href.strip()
                url = clean_url((urljoin(base_url, href)))
                if urlsplit(url)[:2] == urlsplit(base_url)[:2] \
                       and url not in self.history \
                       and url not in self.url_queue:
                    urls.add(url)
        return urls
