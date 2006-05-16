#!/usr/bin/env python
"""Pycreole - a simple web crawler."""

__author__ = "Filip Salomonsson <filip@infix.se>"
__version__ = "0.1a"

import urllib2

USER_AGENT = "pycreole"

if __name__ == '__main__':
    import sys
    from optparse import OptionParser
    import urlparse
    import re
    import os.path
    import md5
    import robotparser

    # Set up and run the option parser
    usage = "usage: %prog [options] URL ..."
    op = OptionParser(usage)
    op.add_option("-d", "--dir", dest="dir", default=".",
                  help="storage directory")
    (options, args) = op.parse_args()

    # We need at least one URL
    if len(args) < 1:
        op.error("no URL given")

    # Clean up the URL (get rid of any fragment identifier)
    url_parts = urlparse.urlsplit(args[0], 'http')
    url = urlparse.urlunsplit(url_parts[:-1] + ('',))

    # Path, including parameters (unique identifier within a host)
    path = urlparse.urlunsplit(('', '') + url_parts[2:-1] + ('',))

    # Host, without default port
    host = re.sub(r':80$', '', url_parts[1])

    # Default request headers
    headers = {'User-Agent': "%s/%s" % (USER_AGENT, __version__)}

    # Parse robots.txt, if available
    rp = robotparser.RobotFileParser()
    request = urllib2.Request("http://%s/robots.txt" % host,
                              headers=headers)
    response = urllib2.urlopen(request)
    rp.parse(response.readlines())

    # Fetch the requested URL, if allowed
    if not rp.can_fetch("%s/%s" % (USER_AGENT, __version__), url):
        raise Exception("Not allowed by robots.txt")
    request = urllib2.Request(url, headers=headers)
    response = urllib2.urlopen(request)

    store_dir = os.path.join(options.dir, host)
    # Create store directory if it doesn't already exist.
    if not os.access(store_dir, os.F_OK):
        os.makedirs(store_dir)
        
    # Store the response
    #@@: might not be the same URL as was requested; doublecheck?
    filename = os.path.join(store_dir, md5.md5(path).hexdigest())
    tmp_filename = filename + ".tmp"
    f = open(tmp_filename, 'w')
    f.write(response.read())
    f.close()
    os.rename(tmp_filename, filename)

    # ..and headers...
    filename = filename + ".headers"
    tmp_filename = filename + "'.tmp"
    f = open(tmp_filename, 'w')
    for (key, value) in sorted(response.info().items()):
        f.write("%s: %s\n" % (key, value))
    f.close()
    os.rename(tmp_filename, filename)

    print >> sys.stderr, "Successfully stored %s" % (url,)
