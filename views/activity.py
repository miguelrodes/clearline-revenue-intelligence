from clearline.config import Settings
from clearline.store import Store
from clearline.monitoring_ui import activity_panel

settings = Settings.load()
store = Store(settings.db_path)
activity_panel(store, settings)
