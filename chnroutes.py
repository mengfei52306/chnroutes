#!/usr/bin/env python

import argparse
import math
import os
import re
import subprocess
import sys
import urllib2

output_dir = None

def generate_ovpn(metric):
    results = fetch_ip_data()

    upscript_header = """\
#!/bin/bash -

export PATH="/bin:/sbin:/usr/sbin:/usr/bin"
OLDGW=$(ip route show 0/0 | head -n1 | grep 'via' | grep -Po '\d+\.\d+\.\d+\.\d+')

ip -batch - <<EOF
"""
    downscript_header = """\
#!/bin/bash -

export PATH="/bin:/sbin:/usr/sbin:/usr/bin"
ip -batch - <<EOF
"""

    upfile = open(os.path.join(output_dir, 'vpn-up.sh'), 'w')
    downfile = open(os.path.join(output_dir, 'vpn-down.sh'), 'w')

    upfile.write(upscript_header)
    downfile.write(downscript_header)

    for ip, _, mask in results:
        upfile.write('route add %s/%s via $OLDGW metric %s\n' % (ip, mask, metric))
        downfile.write('route del %s/%s\n' % (ip, mask))

    upfile.write('EOF\n')
    downfile.write('EOF\n')

    upfile.close()
    downfile.close()

    os.chmod(os.path.join(output_dir, 'vpn-up.sh'), 00755)
    os.chmod(os.path.join(output_dir, 'vpn-down.sh'), 00755)

def generate_old(metric):
    results = fetch_ip_data()

    rfile = open(os.path.join(output_dir, 'routes.txt'),'w')

    rfile.write('max-routes %d\n\n' % (len(results) + 20))

    for ip, mask, _ in results:
        rfile.write("route %s %s net_gateway %d\n" % (ip, mask, metric))

    rfile.close()

def generate_linux(metric):
    results = fetch_ip_data()

    upscript_header = """\
#!/bin/bash -

OLDGW=$(ip route show 0/0 | head -n1 | grep 'via' | grep -Po '\d+\.\d+\.\d+\.\d+')

if [ $OLDGW == '' ]; then
    exit 0
fi

if [ ! -e /tmp/vpn_oldgw ]; then
    echo $OLDGW > /tmp/vpn_oldgw
fi

ip -batch - <<EOF
"""

    downscript_header = """\
#!/bin/bash
export PATH="/bin:/sbin:/usr/sbin:/usr/bin"

OLDGW=$(cat /tmp/vpn_oldgw | head -n1)

ip -batch - <<EOF
"""

    upfile = open(os.path.join(output_dir, 'ip-pre-up'), 'w')
    downfile = open(os.path.join(output_dir, 'ip-down'), 'w')

    upfile.write(upscript_header)
    downfile.write(downscript_header)

    for ip, _, mask in results:
        upfile.write('route add %s/%s via $OLDGW metric %s\n' % (ip, mask, metric))
        downfile.write('route del %s/%s\n' % (ip, mask))

    upfile.write('EOF\n')
    downfile.write('''\
EOF

rm /tmp/vpn_oldgw
''')

    upfile.close()
    downfile.close()

    os.chmod(os.path.join(output_dir, 'ip-pre-up'), 00755)
    os.chmod(os.path.join(output_dir, 'ip-down'), 00755)

def generate_mac(metric):
    results=fetch_ip_data()

    upscript_header = """\
#!/bin/sh
export PATH="/bin:/sbin:/usr/sbin:/usr/bin"

OLDGW=`netstat -nr | grep '^default' | grep -v "$1" | sort -k4 -r | head -n 1 | sed 's/default *\\([0-9\.]*\\) .*/\\1/'`

if [ ! -e /tmp/pptp_oldgw ]; then
    echo "${OLDGW}" > /tmp/pptp_oldgw
fi

dscacheutil -flushcache
"""

    downscript_header = """\
#!/bin/sh
export PATH="/bin:/sbin:/usr/sbin:/usr/bin"

if [ ! -e /tmp/pptp_oldgw ]; then
        exit 0
fi

OLDGW=`cat /tmp/pptp_oldgw | head -n 1`
"""

    upfile = open(os.path.join(output_dir, 'ip-up'),'w')
    downfile = open(os.path.join(output_dir, 'ip-down'),'w')

    upfile.write(upscript_header)
    downfile.write(downscript_header)

    for ip, _, mask in results:
        upfile.write('route add %s/%s "${OLDGW}"\n' % (ip, mask))
        downfile.write('route delete %s/%s ${OLDGW}\n' % (ip, mask))

    downfile.write('\n\nrm /tmp/pptp_oldgw\n')

    upfile.close()
    downfile.close()

    os.chmod(os.path.join(output_dir, 'ip-up'), 00755)
    os.chmod(os.path.join(output_dir, 'ip-down'), 00755)

def generate_routeros(metric):
    results=fetch_ip_data()

    downscript_header = """\
:foreach i in=[/ip route rule find action="lookup" and table="chnroutes"] do={
    /ip route remove $i
}
"""

    scriptfile = open(os.path.join(output_dir, 'chnroutes.rsc'),'w')
    scriptfile.write(downscript_header)

    for ip, _, mask in results:
        scriptfile.write('/ip route rule add action="lookup" table="chnroutes" dst-address="%s/%s"\n' % (ip, mask))

    scriptfile.close()


def generate_win(metric):
    results = fetch_ip_data()

    upscript_header = """\
@echo off
for /F "tokens=3" %%* in ('route print ^| findstr "\\<0.0.0.0\\>"') do set "gw=%%*"
"""

    upfile = open(os.path.join(output_dir, 'vpnup.bat'),'w')
    downfile = open(os.path.join(output_dir, 'vpndown.bat'),'w')

    upfile.write(upscript_header)
    upfile.write('ipconfig /flushdns\n\n')

    downfile.write("@echo off")
    downfile.write('\n')

    for ip, mask, _ in results:
        upfile.write('route add %s mask %s %s metric %d\n' % (ip, mask, "%gw%", metric))
        downfile.write('route delete %s\n' % ip)

    upfile.close()
    downfile.close()

def generate_android(metric):
    results = fetch_ip_data()
    
    upscript_header=textwrap.dedent("""\
    #!/bin/sh
    alias nestat='/system/xbin/busybox netstat'
    alias grep='/system/xbin/busybox grep'
    alias awk='/system/xbin/busybox awk'
    alias route='/system/xbin/busybox route'
    
    OLDGW=`netstat -rn | grep ^0\.0\.0\.0 | awk '{print $2}'`
    
    """)
    
    downscript_header=textwrap.dedent("""\
    #!/bin/sh
    alias route='/system/xbin/busybox route'
    
    """)
    
    upfile=open(os.path.join(output_dir, 'vpnup.sh'),'w')
    downfile=open(os.path.join(output_dir, 'vpndown.sh'),'w')
    
    upfile.write(upscript_header)
    upfile.write('\n')
    downfile.write(downscript_header)
    downfile.write('\n')
    
    for ip,mask,_ in results:
        upfile.write('route add -net %s netmask %s gw $OLDGW\n'%(ip,mask))
        downfile.write('route del -net %s netmask %s\n'%(ip,mask))
    
    upfile.close()
    downfile.close()
    
    print "Old school way to call up/down script from openvpn client. " \
          "use the regular openvpn 2.1 method to add routes if it's possible"

def fetch_ip_data():
    url = 'http://ftp.apnic.net/apnic/stats/apnic/delegated-apnic-latest'
    try:
        data = subprocess.check_output(['wget', url, '-O-'])
    except (OSError, AttributeError):
        print >>sys.stderr, "Fetching data from apnic.net, it might take a few minutes, please wait..."
        data = urllib2.urlopen(url).read()

    cnregex = re.compile(r'^apnic\|cn\|ipv4\|[\d\.]+\|\d+\|\d+\|a\w*$', re.I | re.M)
    cndata = cnregex.findall(data)

    results = []

    # from local file
    if os.path.exists('/etc/chnroutes'):
      f = open('/etc/chnroutes')
      for line in f:
        starting_ip, mask, cidr = line.strip().split('|')
        results.append((starting_ip, mask, cidr))

    for item in cndata:
        unit_items = item.split('|')
        starting_ip = unit_items[3]
        num_ip = int(unit_items[4])

        imask = 0xffffffff ^ (num_ip - 1)
        imask = hex(imask)[2:]

        mask = [imask[i:i + 2] for i in xrange(0, 8, 2)]
        mask = '.'.join([str(int(i, 16)) for i in mask])

        cidr = 32 - int(math.log(num_ip, 2))

        results.append((starting_ip, mask, cidr))

    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Generate routing rules for VPN users in China.")
    parser.add_argument('-p',
                        dest='platform',
                        default='openvpn',
                        nargs='?',
                        choices=['openvpn', 'old', 'mac', 'linux', 'win', 'routeros'],
                        help="target platform")
    parser.add_argument('-m',
                        dest='metric',
                        default=5,
                        nargs='?',
                        type=int,
                        help="metric")
    parser.add_argument('-o',
                        dest='output',
                        default=".",
                        nargs='?',
                        help='output directory')

    args = parser.parse_args()
    output_dir = args.output

    if args.platform.lower() == 'openvpn':
        generate_ovpn(args.metric)
    elif args.platform.lower() == 'old':
        generate_old(args.metric)
    elif args.platform.lower() == 'linux':
        generate_linux(args.metric)
    elif args.platform.lower() == 'mac':
        generate_mac(args.metric)
    elif args.platform.lower() == 'routeros':
        generate_routeros(args.metric)
    elif args.platform.lower() == 'win':
        generate_win(args.metric)
    elif args.platform.lower() == 'android':
        generate_android(args.metric)
    else:
        exit(1)
