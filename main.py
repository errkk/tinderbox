#!/usr/bin/env python
"""
    Proxy server to automate part of the Tinder experience, augmenting the
    statistical imparement that the whole game revolves around.
"""

from __future__ import unicode_literals

import socket
import requests
import redis
import json
import os

from libmproxy import proxy, flow
from pprint import pprint


""" SETTINGS """
PORT = 8889
OVERRIDE_LOCATION = True
AUTOLIKE = False

conn = redis.Redis()

try:
    response = conn.client_list()
except redis.ConnectionError:
    raise Exception('Please ensure redis server is running')

SIGNGAPORE = {u'lat': 1.290301, u'lon': 103.844555}
TOKYO =  {u'lat': 35.678403, u'lon': 139.670506}
PARIS =  {u'lat': 48.856614, u'lon': 2.352222}
NYC =  {u'lat': 40.738187, u'lon': -74.005204}
LOCATION = NYC

URL = 'https://api.gotinder.com'

HEADERS = {
    'Accept-Language': 'en-GB;q=1, en;q=0.9, fr;q=0.8, de;q=0.7, ja;q=0.6, nl;q=0.5',
    'User-Agent': 'Tinder/3.0.3 (iPhone; iOS 7.0.6; Scale/2.00)',
    'os_version': '70000000006',
    'Accept': '*/*',
    'platform': 'ios',
    'Connection': 'keep-alive',
    'Proxy-Connection': 'keep-alive',
    'app_version': '1',
    'Accept-Encoding': 'gzip, deflate',
}

class MyMaster(flow.FlowMaster):
    token = None

    def run(self):
        try:
            flow.FlowMaster.run(self)
        except Exception, e:
            print e
            self.shutdown()
        except KeyboardInterrupt:
            self.shutdown()


    def handle_request(self, msg):
        """ Intercept a request on the way out from the phone, modifying
        payload where necessary
        """
        f = flow.FlowMaster.handle_request(self, msg)
        if f:
            # Phone checking in with location, it may be modified here
            if '/ping' in f.request.path:
                if OVERRIDE_LOCATION:
                    f.request.content = json.dumps(LOCATION)
                    print 'Modifed location to:', f.request.content

        msg.reply()
        return f

    def handle_response(self, msg):
        """ Intercepted responses, requested from the App.
        They get sent back to the phone
        """
        f = flow.FlowMaster.handle_response(self, msg)
        if f:

            # Initial recs request, triggered by the app
            if '/recs' in f.request.path:
                self.handle_response_recs(f.request, f.response)

            # Copy the token when it authenticates
            elif '/auth' == f.request.path:
                data = json.loads(f.response.content)
                token = data['token']
                self.token = token
                print '> Setting Token: {0}'.format(token)

            # See what it says about location
            elif '/ping' == f.request.path:
                data = json.loads(f.response.content)
                print data

            # Updates from the server about state changes
            elif '/updates' == f.request.path:
                data = json.loads(f.response.content)
                matches = data.get('matches', [])
                if len(matches):
                    print '** CODE RED **'
                    print 'Matches', len(matches)
                    for m in matches:
                        name = m['person']['name']
                        print '- {0}'.format(name)
        msg.reply()

        return f

    def handle_response_recs(self, request, response):
        """ Handle the initial Recs response, requested by the phone.
        This kicks off the auto liking process
        """
        print 'Initial Recs request, from app'
        recs = json.loads(response.content)
        self.do_likes(recs)

    def do_likes(self, recs):
        """ Process recs, send auto like requests to all of them
        """
        if 200 != recs['status']:
            print 'Fail', recs['status']
            return

        for i in recs['results']:
            id = i['_id']
            conn.set(id, json.dumps(i))
            name, common_friends = unicode(i['name']), i['common_friend_count']
            if int(common_friends) > 0:
                print 'Ohh, {0} knows {1} people that you do'.format(name,
                        common_friends)
                print id

            if AUTOLIKE:
                self.send_like(id)

        print '> Batch complete'

        if AUTOLIKE:
            self.get_more_recs()

    def get_more_recs(self):
        """ Automatically retrieve the next batch of recommendations
        """
        print '> Getting more recs'
        path = os.path.join(URL, 'recs')
        r = requests.get(path, headers=self.get_headers())
        print r.status_code
        if 200 == r.status_code:
            recs = r.json()
            self.do_likes(recs)

    def send_like(self, id):
        """ Send automatic Like request
        """
        name = ''
        person = conn.get(id)
        if person:
            person = json.loads(person)
            name = person['name']

        path = os.path.join(URL, 'like', id)
        r = requests.get(path, headers=self.get_headers())

        res = r.json()

        if res['match']:
            print '=' * 80
            print '*** Holy Fucking shit! Match from {0} ***'.format(name)
            print '=' * 80
        else:
            print 'Nope {0}'.format(name)

    def get_headers(self):
        if not self.token:
            return False
        headers = HEADERS
        headers['X-Auth-Token'] = self.token
        headers['Authorization'] = 'Token token="{0}"'.format(self.token)
        return headers


if __name__ == '__main__':
    config = proxy.ProxyConfig(
        cacert = os.path.expanduser("~/.mitmproxy/mitmproxy-ca.pem")
    )
    state = flow.State()

    server = proxy.ProxyServer(config, PORT)

    print '> Proxying on {0}'.format(PORT)

    m = MyMaster(server, state)
    m.run()
