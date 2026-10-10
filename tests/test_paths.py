from weibo_downloader.paths import application_dir, default_download_dir


def test_default_download_dir_is_under_application_directory() -> None:
    output_dir = default_download_dir()

    assert output_dir.is_absolute()
    assert output_dir == application_dir() / "downloads"
