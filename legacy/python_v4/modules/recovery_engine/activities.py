"""Pure-Python mini-activity logic; visual scenes belong to frontend/3D team."""
import random
class ZeroGGarden:
 def __init__(self):self.growth=0.0
 def interact(self,breath_quality=None):
  self.growth+=max(0,min(1,float(breath_quality))) if breath_quality is not None else 0.1
  return {'growth':round(self.growth,3),'scene_parameter':'plant_growth','synthetic_feedback':breath_quality is None}
class EarthWindow:
 def __init__(self):self.preferences={}
 def finish(self,environment,minutes,mood_before,mood_after):
  result={'environment':environment,'duration_minutes':minutes,'before':mood_before,'after':mood_after}
  self.preferences.setdefault(environment,[]).append(result);return result
class OrbitFlow:
 def __init__(self,seed=13):self.rng=random.Random(seed);self.level=1;self.correct=0;self.total=0
 def question(self):
  a=self.rng.randint(1,4*self.level);b=self.rng.randint(1,4*self.level)
  return {'prompt':f'{a} + {b}','answer':a+b,'level':self.level}
 def submit(self,question,answer):
  ok=answer==question['answer'];self.total+=1;self.correct+=int(ok)
  if self.total%3==0:self.level=max(1,min(10,self.level+(1 if self.correct/self.total>=.8 else -1)))
  return {'correct':ok,'level':self.level,'accuracy':self.correct/self.total}
class MindPulse:
 def score(self,reaction_ms,correct,total):
  if total<=0 or correct<0 or correct>total or reaction_ms<0:raise ValueError('Invalid test result')
  return {'reaction_ms':reaction_ms,'accuracy':correct/total,'validated_clinical_test':False}
