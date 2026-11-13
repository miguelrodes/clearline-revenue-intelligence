from clearline.config import Settings
from clearline.store import Store
from clearline.prospect_ui import prospect_panel

settings = Settings.load()
store = Store(settings.db_path)
prospect_panel(store, settings)
