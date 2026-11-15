import argparse
import csv
import json
from pathlib import Path
from .mission_lab.scenarios import demo,SCENARIOS
from .mission_lab.simulator import Simulator
from .mission_lab.generator import generate
from .mission_lab.experiments import phantom_input,experiment_report
from .co_orbit.scheduler import solve
from .symbiosis.environment import sample_environment
from .symbiosis.scenarios import compare_conditions
from .contracts import Environment,Scenario
from .storage import Store


def write_json(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def main(argv=None):
    parser=argparse.ArgumentParser(description='AETHER Mission Systems — local synthetic research')
    parser.add_argument('command',choices=['demo','suite','symbiosis','co-orbit','mission-lab','serve'])
    parser.add_argument('--scenario',choices=SCENARIOS,default='normal')
    parser.add_argument('--config',type=Path)
    parser.add_argument('--output',type=Path,default=Path('outputs'))
    parser.add_argument('--db',type=Path,default=None)
    parser.add_argument('--interactive',action='store_true',help='Offline terminal controls for mission-lab/demo')
    args=parser.parse_args(argv)
    if args.command=='serve':
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(args.db),host='127.0.0.1',port=8000);return
    s=Scenario.model_validate_json(args.config.read_text(encoding='utf-8')) if args.config else demo(args.scenario)
    if args.command=='symbiosis':
        print(json.dumps(compare_conditions(s.environment,Environment(),sleep_a=6,sleep_b=8),indent=2));return
    if args.command=='co-orbit':
        print(json.dumps(solve(s.planning),indent=2));return
    args.output.mkdir(parents=True,exist_ok=True)
    if args.command=='suite':
        reports={}
        for name in SCENARIOS:
            scenario=demo(name);schedule=solve(scenario.planning);dataset=generate(scenario,schedule)
            folder=args.output/name;folder.mkdir(exist_ok=True)
            write_json(folder/'scenario.json',scenario.model_dump(mode='json'))
            write_json(folder/'phantom_input.json',phantom_input(dataset))
            write_json(folder/'ground_truth.json',dataset['ground_truth'])
            reports[name]=experiment_report(dataset)
        write_json(args.output/'evaluation.json',reports)
        print(f'Generated {len(SCENARIOS)} labeled scenarios in {args.output.resolve()}');return
    sim=Simulator(s,Store(args.db));sim.save()
    write_json(args.output/'scenario.json',s.model_dump(mode='json'))
    write_json(args.output/'dataset.json',sim.dataset)
    write_json(args.output/'phantom_input.json',phantom_input(sim.dataset))
    write_json(args.output/'ground_truth.json',sim.dataset['ground_truth'])
    write_json(args.output/'schedules.json',sim.schedules)
    write_json(args.output/'evaluation.json',experiment_report(sim.dataset))
    flat=[r for f in sim.dataset['frames'] for r in f['measurements']+f['environment']]
    with (args.output/'measurements.csv').open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(flat[0]));writer.writeheader();writer.writerows(flat)
    print(f'Completed {s.id}: {len(sim.dataset["frames"])} frames. Results: {args.output.resolve()}')
    print('PHANTOM not connected; evaluation contains threshold comparator results only.')
    if args.interactive:
        print('Commands: start, pause, resume, reset, seek MINUTE, speed FACTOR, tick SECONDS, save, state, quit')
        while True:
            try:
                parts=input('mission> ').strip().split()
                if not parts: continue
                action=parts[0]
                if action=='quit': break
                if action=='save': sim.save()
                elif action in ('start','pause','resume','reset'): getattr(sim,action)()
                elif action in ('seek','speed','tick'):
                    if len(parts)!=2: raise ValueError('A numeric value is required')
                    method=sim.set_speed if action=='speed' else getattr(sim,action)
                    method(float(parts[1]))
                elif action!='state': raise ValueError('Unknown command')
                print(json.dumps({k:v for k,v in sim.state().items() if k in ('status','minute','speed','phantom_status')}))
            except (ValueError,EOFError,KeyboardInterrupt) as exc:
                if isinstance(exc,(EOFError,KeyboardInterrupt)): break
                print(str(exc))

if __name__=='__main__':main()
