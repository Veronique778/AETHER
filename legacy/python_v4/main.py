"""AETHER interactive Kivy demonstration. Works offline with explicitly synthetic readings.
This is a new native dashboard, NOT a pixel-perfect extraction of the Windows installer.
"""
from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle, Line
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.spinner import Spinner
from kivy.uix.screenmanager import ScreenManager, Screen, FadeTransition
from core.theme import BG,PANEL,TEXT,MUTED,ACCENT
from services.live_demo import DemoSystem

SECTIONS=['OVERVIEW','BODY','PHANTOM','SYMBIOSIS','CO-ORBIT','RECOVERY','MISSION LAB']

def label(value,size=15,color=TEXT,height=36):
 w=Label(text=str(value),font_size=size,color=color,markup=True,size_hint_y=None,height=height,halign='left',valign='middle')
 w.bind(width=lambda obj,v:setattr(obj,'text_size',(max(1,v-8),None)))
 return w

def button(text,fn=None):
 w=Button(text=text,size_hint_y=None,height=45,background_normal='',background_color=ACCENT,color=BG,font_size=14)
 if fn:w.bind(on_release=lambda *_:fn())
 return w

class Panel(BoxLayout):
 def __init__(self,**kw):
  super().__init__(orientation='vertical',padding=14,spacing=6,size_hint_y=None,**kw)
  self.bind(minimum_height=self.setter('height'))
  with self.canvas.before:
   Color(*PANEL);self.rect=RoundedRectangle(pos=self.pos,size=self.size,radius=[12])
  self.bind(pos=self._update,size=self._update)
 def _update(self,*_):self.rect.pos=self.pos;self.rect.size=self.size

class Placeholder(BoxLayout):
 """Explicit 3D placeholder, not an actual rendered mesh."""
 def __init__(self,kind,**kw):
  super().__init__(orientation='vertical',size_hint_y=None,height=165,**kw)
  with self.canvas.before:
   Color(.07,.16,.25,1);self.bg=RoundedRectangle(pos=self.pos,size=self.size,radius=[12])
   Color(*ACCENT);self.outline=Line(rectangle=(self.x+25,self.y+25,max(1,self.width-50),max(1,self.height-50)),width=1)
  self.bind(pos=self._draw,size=self._draw)
  self.add_widget(label('3D '+kind+' — MODEL PLACEHOLDER',16,ACCENT,65))
  self.add_widget(label('Replace with approved 3D assets and renderer.',12,MUTED,50))
 def _draw(self,*_):
  self.bg.pos=self.pos;self.bg.size=self.size
  self.outline.rectangle=(self.x+15,self.y+15,max(1,self.width-30),max(1,self.height-30))

class Dashboard(Screen):
 def __init__(self,system,**kw):
  super().__init__(**kw);self.system=system;self.section='OVERVIEW'
  self.root=BoxLayout(orientation='vertical',padding=12,spacing=8);self.add_widget(self.root)
  self.root.add_widget(label('[b]AETHER[/b]  /  MISSION CONTROL',25,ACCENT,44))
  self.root.add_widget(label('OFFLINE RESEARCH DEMO  •  SYNTHETIC DATA',12,MUTED,27))
  nav=ScrollView(size_hint_y=None,height=51,do_scroll_y=False)
  self.nav=BoxLayout(orientation='horizontal',spacing=5,size_hint_x=None)
  self.nav.bind(minimum_width=self.nav.setter('width'))
  for section in SECTIONS:
   b=Button(text=section,size_hint=(None,None),width=max(95,len(section)*10+18),height=44,background_normal='',background_color=PANEL,color=TEXT)
   b.bind(on_release=lambda _,s=section:self.show(s));self.nav.add_widget(b)
  nav.add_widget(self.nav);self.root.add_widget(nav)
  scroll=ScrollView();self.content=BoxLayout(orientation='vertical',spacing=10,size_hint_y=None)
  self.content.bind(minimum_height=self.content.setter('height'));scroll.add_widget(self.content);self.root.add_widget(scroll)
  self.footer=label('',12,MUTED,28);self.root.add_widget(self.footer)
  self.show('OVERVIEW')
 def card(self,title,rows):
  p=Panel();p.add_widget(label('[b]'+title+'[/b]',18,ACCENT,39))
  for row in rows:p.add_widget(label(row,14,TEXT,38))
  self.content.add_widget(p);return p
 def show(self,section=None):
  if section:self.section=section
  self.content.clear_widgets();s=self.system.snapshot();m=s['metrics'];env=s['environment'];a=s['analysis']
  self.footer.text=f"MISSION DAY {s['mission']['day']}  •  {s['mission']['scenario'].upper()}  •  DATA: SYNTHETIC"
  def val(k,unit=''):
   r=m.get(k);return (f"{r['value']:.1f} {unit or r['unit']}" if r else 'No data')
  if self.section in ('OVERVIEW','BODY'):
   self.card('BIOMETRIC MONITORING',[
    f"Heart rate: {val('heart_rate')}",f"Resting HR: {val('resting_hr')}",
    f"Sleep: {val('sleep_hours')}",f"Fatigue: {val('fatigue')}",
    f"Reaction time: {val('reaction_ms')}",f"Activity: {val('activity_minutes')}"])
   self.content.add_widget(Placeholder('HUMAN'))
  if self.section in ('OVERVIEW','PHANTOM'):
   self.card('PHANTOM  /  PATTERN ANALYSIS',[
    f"Status: {a['status']}",f"Alerts: {len(a['alerts'])}",
    f"Data completeness: {a['uncertainty'].get('completeness','not available')}",
    'Not a diagnosis. Alerts are research indicators.'])
   for alert in a['alerts'][-4:]:self.card('PATTERN / '+alert['type'],[alert['explanation']])
   if not a['alerts']:self.card('EXPLANATION',['No pattern detected, or insufficient data.'])
  if self.section in ('OVERVIEW','SYMBIOSIS'):
   self.card('SYMBIOSIS  /  CABIN ENVIRONMENT',[
    f"Temperature: {env['temperature_c']} C",f"Humidity: {env['humidity_pct']} %",
    f"CO2: {env['co2_ppm']} ppm",f"Oxygen: {env['oxygen_pct']} %"])
   self.content.add_widget(Placeholder('SPACECRAFT'))
  if self.section=='CO-ORBIT':
   for task in s['tasks']:
    p=self.card('CREW TASK '+str(task['id']),[task['title'],f"Assigned: {task['assigned_to']} / {task['status']}"])
    p.add_widget(button('TOGGLE TASK STATUS',lambda tid=task['id']:self.task(tid)))
  if self.section=='RECOVERY':
   self.card('RECOVERY LAB',['Choose an activity. Self-report values are synthetic demo inputs.'])
   for name in ('Zero-G Garden','Earth Window','Orbit Flow','Mind Pulse'):
    p=Panel();p.add_widget(label(name,17,ACCENT,36));p.add_widget(button('RUN DEMO SESSION',lambda n=name:self.run_recovery(n)));self.content.add_widget(p)
   for r in s['recovery_suggestions']:
    self.card('PERSONAL PATTERN',[f"{r['activity']}: {r['mean_self_report_change']:+.1f} self-report change",r['caution']])
  if self.section=='MISSION LAB':
   self.card('SCENARIO CONTROL',['Each step advances a simulated mission day and saves new measurements.'])
   p=Panel();p.add_widget(button('NOMINAL',lambda:self.scenario('nominal')))
   p.add_widget(button('SLEEP DEBT',lambda:self.scenario('sleep_debt')))
   p.add_widget(button('CABIN CO2 DRIFT',lambda:self.scenario('cabin_co2')))
   p.add_widget(button('ADVANCE ONE DAY',self.advance));self.content.add_widget(p)
  if self.section=='OVERVIEW':
   p=Panel();p.add_widget(button('ADVANCE MISSION DAY',self.advance));p.add_widget(button('OPEN MISSION LAB',lambda:self.show('MISSION LAB')));self.content.add_widget(p)
 def advance(self):self.system.tick();self.show()
 def scenario(self,name):self.system.scenario(name);self.show()
 def task(self,tid):self.system.toggle_task(tid);self.show()
 def run_recovery(self,name):
  result=self.system.recovery(name,5,6);self.show()
  self.card('LATEST SESSION', [name, str(result)[:180]])

class AetherApp(App):
 def build(self):
  self.title='AETHER / Mission Control';self.system=DemoSystem()
  manager=ScreenManager(transition=FadeTransition());manager.add_widget(Dashboard(self.system,name='dashboard'));return manager
 def on_stop(self):self.system.close()

if __name__=='__main__':AetherApp().run()
