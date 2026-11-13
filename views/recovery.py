from clearline.config import Settings
from clearline.store import Store
from clearline.recovery_ui import recovery_panel

settings = Settings.load()
store = Store(settings.db_path)
recovery_panel(store, settings)
