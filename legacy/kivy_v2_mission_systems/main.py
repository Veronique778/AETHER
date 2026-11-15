from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.graphics import Color, RoundedRectangle
from core.database import init_db
from core.theme import BG, PANEL, TEXT, MUTED, ACCENT
from modules.body import body_summary
from modules.phantom import phantom_summary
from modules.symbiosis import symbiosis_summary
from modules.coorbit import coorbit_summary
from modules.recovery import recovery_summary
from modules.mission_lab import mission_summary

MODULES = [
    ("BODY", body_summary),
    ("PHANTOM", phantom_summary),
    ("SYMBIOSIS", symbiosis_summary),
    ("CO-ORBIT", coorbit_summary),
    ("RECOVERY", recovery_summary),
    ("MISSION LAB", mission_summary),
]

class Panel(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.padding = 16
        self.spacing = 10
        with self.canvas.before:
            Color(*PANEL)
            self.bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[14])
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *_):
        self.bg.pos, self.bg.size = self.pos, self.size

def label(text, size=14, color=TEXT, height=None, bold=False):
    return Label(text=text, font_size=size, color=color, bold=bold,
                 size_hint_y=None if height else 1, height=height or 40,
                 halign="left", valign="middle", text_size=(None, None))

class HomeScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        outer = BoxLayout(orientation="vertical", padding=18, spacing=12)
        outer.add_widget(label("AETHER", 30, ACCENT, 48))
        outer.add_widget(label("ADAPTIVE ECOSYSTEM FOR HUMAN EXPLORATION AND RESILIENCE",
                               10, MUTED, 28))
        status = GridLayout(cols=2, spacing=10, size_hint_y=None, height=92)
        for heading, value in (("MISSION DAY", "67"), ("SYSTEM STATUS", "STABLE")):
            p = Panel()
            p.add_widget(label(heading, 11, MUTED))
            p.add_widget(label(value, 22, TEXT, bold=True))
            status.add_widget(p)
        outer.add_widget(status)
        outer.add_widget(label("FUNCTIONAL MODULES", 13, MUTED, 28, True))
        scroll = ScrollView()
        grid = GridLayout(cols=1, spacing=9, size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        for name, summary in MODULES:
            btn = Button(text=f"{name}\n{summary()}",
                         size_hint_y=None, height=76,
                         background_normal="", background_color=PANEL,
                         color=TEXT, halign="center")
            btn.bind(on_release=lambda instance, n=name: self.open_module(n))
            grid.add_widget(btn)
        scroll.add_widget(grid)
        outer.add_widget(scroll)
        footer = label("AETHER CORE  •  LOCAL MODE", 10, MUTED, 24)
        outer.add_widget(footer)
        self.add_widget(outer)

    def open_module(self, name):
        self.manager.current = name.lower().replace(" ", "_").replace("-", "")

class ModuleScreen(Screen):
    def __init__(self, module_name, description, **kwargs):
        super().__init__(**kwargs)
        self.module_name = module_name
        layout = BoxLayout(orientation="vertical", padding=18, spacing=14)
        layout.add_widget(label("AETHER  /  " + module_name, 22, ACCENT, 46, True))
        card = Panel()
        card.add_widget(label("MODULE OVERVIEW", 12, MUTED, 28, True))
        card.add_widget(label(description, 15, TEXT, 100))
        card.add_widget(label("This module is ready for independent development.",
                              12, MUTED, 50))
        layout.add_widget(card)
        back = Button(text="<- BACK TO DASHBOARD", size_hint_y=None, height=48,
                      background_normal="", background_color=ACCENT, color=BG)
        back.bind(on_release=lambda *_: setattr(self.manager, "current", "home"))
        layout.add_widget(back)
        self.add_widget(layout)

class AetherApp(App):
    def build(self):
        self.title = "AETHER"
        init_db()
        manager = ScreenManager(transition=SlideTransition())
        manager.add_widget(HomeScreen(name="home"))
        descriptions = {
            "BODY": "Physiological measurements, personal indicators, trends and measurement history. 3D visualization is intentionally omitted.",
            "PHANTOM": "Analysis of time series, personal baselines, anomaly detection and uncertainty-aware explanations.",
            "SYMBIOSIS": "Monitoring of cabin temperature, humidity, lighting, CO2 and other environment parameters.",
            "CO-ORBIT": "Crew profiles, tasks, schedules and workload planning using permitted data only.",
            "RECOVERY": "Recovery activities, session history and before/after self-reported or measured indicators.",
            "MISSION LAB": "Mission scenario generation with synthetic physiological and environmental data."
        }
        for name, _ in MODULES:
            screen_name = name.lower().replace(" ", "_").replace("-", "")
            manager.add_widget(ModuleScreen(name, descriptions[name], name=screen_name))
        return manager

if __name__ == "__main__":
    AetherApp().run()
