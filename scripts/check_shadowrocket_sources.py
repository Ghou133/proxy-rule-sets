#!/usr/bin/env python3
"""Audit complete remote files without vendoring third-party rule content."""
import hashlib
import ipaddress
import json
from collections import Counter
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from build_shadowrocket import ROOT, SOURCES
from update_rules import write


def fetch(url):
    with urlopen(Request(url, headers={"User-Agent":"proxy-rule-sets-audit"}), timeout=45) as response:
        data = response.read()
    if not data: raise ValueError("Empty upstream download")
    return data


def audit(content, domain_set=False):
    counts = Counter()
    for number,line in enumerate(content.decode('utf-8-sig').splitlines(),1):
        line = line.strip()
        if not line or line.startswith(('#',';','//')): continue
        if domain_set:
            if any(c.isspace() for c in line) or any(c in line for c in '/:,'):
                raise ValueError(f"Invalid DOMAIN-SET syntax at line {number}")
            counts['DOMAIN-SET-ENTRY'] += 1
            continue
        fields = [x.strip() for x in line.split(',')]
        kind = fields[0]
        if kind not in {'DOMAIN','DOMAIN-SUFFIX','DOMAIN-KEYWORD','IP-CIDR','IP-CIDR6','USER-AGENT'}:
            raise ValueError(f"Unexpected rule type at line {number}: {kind}")
        if len(fields) < 2 or len(fields) > 3 or (len(fields)==3 and fields[2]!='no-resolve'):
            raise ValueError(f"Unexpected policy or parameters at line {number}")
        if kind.startswith('DOMAIN'):
            if any(c.isspace() for c in fields[1]) or '/' in fields[1] or ':' in fields[1]:
                raise ValueError(f"Invalid domain syntax at line {number}")
        if kind in {'IP-CIDR','IP-CIDR6'}: ipaddress.ip_network(fields[1],strict=False)
        counts[kind]+=1
    if not counts: raise ValueError('No rules found')
    return dict(sorted(counts.items()))


def main():
    path=ROOT/'clients/shadowrocket/sources.json'
    previous=json.loads(path.read_text('utf-8')) if path.exists() else []
    old={x['url']:x for x in previous}
    heads={}
    records=[]
    for purpose,url in SOURCES.items():
        parts=url.split('/')
        repository='/'.join(parts[3:5]); branch=parts[5]; file='/'.join(parts[6:])
        if repository not in heads:
            head=json.loads(fetch(f'https://api.github.com/repos/{repository}/commits/{branch}'))
            heads[repository]=(head['sha'],head['commit']['committer']['date'])
        commit,date=heads[repository]
        content=fetch(f'https://raw.githubusercontent.com/{repository}/{commit}/{file}')
        types=audit(content, domain_set=purpose=='ChinaDomain')
        record={'purpose':purpose,'url':url,'repository':repository,'branch':branch,'commit':commit,
                'repository_commit_at':date,'sha256':hashlib.sha256(content).hexdigest(),
                'rule_count':sum(types.values()),'types':types,'materialized':False}
        prior=old.get(url,{})
        record['fetched_at']=prior.get('fetched_at') if all(prior.get(k)==v for k,v in record.items()) else datetime.now(timezone.utc).isoformat()
        records.append(record)
    write(path,json.dumps(records,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({x['purpose']:x['rule_count'] for x in records}))


if __name__=='__main__': main()
