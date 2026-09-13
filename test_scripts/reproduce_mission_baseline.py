"""Read-only reproduction against release-prep sources; never calls a model/tool."""
import asyncio
import subprocess
from unittest.mock import patch
from google.genai import types


async def main():
    namespace={'__name__':'baseline_missions'}
    exec(subprocess.check_output(['git','show','release-prep:core/missions.py']).decode('utf-8'),namespace)
    with patch('google.genai.Client',side_effect=RuntimeError('simulated verifier outage')):
        result=await namespace['MissionOrchestrator']()._verify_step(
            namespace['Mission']('test','test'),namespace['MissionStep'](1,'test','test'),[],{})
    print('BASELINE verifier outage certified success:',result[0])
    agents={'__name__':'baseline_agents'}
    exec(subprocess.check_output(['git','show','release-prep:core/agents.py']).decode('utf-8'),agents)
    from core import registry
    fake={'disabled':{'decl':types.FunctionDeclaration(name='disabled',description='test'), 'gate':'test.enabled'}}
    with patch.object(registry,'build_declarations',return_value=[]),patch.object(registry,'_REGISTRY',fake):
        declarations=agents['_declarations']({'tools':['disabled']},{'test':{'enabled':False}})
    print('BASELINE disabled tool advertised:',bool(declarations))
    with patch('google.genai.Client'),patch.dict(agents,{'_declarations':lambda *a:[]}):
        result=await agents['react_loop']('test','test',[],'test',{},registry.ToolContext({}),max_steps=0)
    print('BASELINE exhausted executor returned ordinary text:',isinstance(result,str))


if __name__=='__main__':asyncio.run(main())
