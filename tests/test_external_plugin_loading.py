import os
import asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugin_loader import PluginLoader


def test_external_plugin_loading_minimal():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    plugin_dir = os.path.join(repo_root, 'example_external_plugin')
    assert os.path.isdir(plugin_dir), f"example_external_plugin not found at {plugin_dir}"

    os.environ['PLUGINS_DIR'] = plugin_dir

    app = FastAPI()
    # db_session_maker not needed for this example plugin
    loader = PluginLoader(app, None)

    # load plugins (async)
    asyncio.run(loader.load_all())

    with TestClient(app) as client:
        r = client.get('/api/v1/admin/plugins')
        assert r.status_code == 200
        data = r.json()
        assert 'plugins' in data

        r2 = client.get('/api/v1/plugins/weather_plugin/status')
        assert r2.status_code == 200, r2.text
        j = r2.json()
        assert j.get('plugin') == 'weather'
