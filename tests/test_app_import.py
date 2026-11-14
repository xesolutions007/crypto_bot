def test_fastapi_app_imports_with_scanner_configuration():
    import bot_master

    assert bot_master.app.title == "Multi-Exchange Trading Module Bot"
    assert bot_master.SCAN_INTERVAL_SECONDS >= 10
