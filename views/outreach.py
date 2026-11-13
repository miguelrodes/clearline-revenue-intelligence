from clearline.config import Settings
from clearline.store import Store
from clearline.monitoring_ui import outreach_panel

settings = Settings.load()
store = Store(settings.db_path)
outreach_panel(store)
