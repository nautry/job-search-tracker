"""Search the last collected feed locally. Does not submit applications."""
import argparse
import json
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('query',nargs='?',default='',help='Words in title, company, city or matching evidence')
    p.add_argument('--company',default='')
    p.add_argument('--city',default='')
    p.add_argument('--min-score',type=int,default=40)
    p.add_argument('--include-deprioritized',action='store_true')
    p.add_argument('--limit',type=int,default=25)
    p.add_argument('--interactive',action='store_true',help='Prompt for search words')
    args=p.parse_args()
    if args.interactive: args.query=input('Search words (blank for top results): ').strip()
    path=Path(__file__).resolve().parents[1]/'data/jobs.json'
    if not path.exists():p.error('Run python -m src.puller first.')
    feed=json.loads(path.read_text())
    count=0
    for j in feed['jobs']:
        hay=' '.join(str(j.get(k,'')) for k in ['title','company','location','evidence']).lower()
        if not all(w in hay for w in args.query.lower().split()):continue
        if args.company.lower() not in j['company'].lower() or args.city.lower() not in j['location'].lower():continue
        if j['role_score']<args.min_score:continue
        if not args.include_deprioritized and j['location_fit']=='Deprioritized region':continue
        print(f"{j['company']} | {j['title']}\n{j['location']} | role {j['role_score']}/100 | {j['experience']}\n{j['availability']}\n{j['url']}\n")
        count+=1
        if count>=args.limit:break
    print(f'{count} results shown. Feed: {feed["generated_at"]}')

if __name__=='__main__':main()
