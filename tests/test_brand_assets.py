from jarvis.core.brand import (
    BRAND_DIRECTORY_NAME,
    PACKAGE_ASSETS,
    brand_asset_directory,
    resolve_brand_assets,
)


def test_the_brand_asset_directory_is_brand_under_the_home(tmp_path):
    assert brand_asset_directory(tmp_path) == tmp_path / BRAND_DIRECTORY_NAME
    assert BRAND_DIRECTORY_NAME == "brand"


def test_without_a_brand_directory_the_package_defaults_are_used(tmp_path):
    assets = resolve_brand_assets(tmp_path)

    assert assets.png == PACKAGE_ASSETS / "jarvis.png"
    assert assets.ico == PACKAGE_ASSETS / "jarvis.ico"
    assert assets.png.is_file()
    assert assets.ico.is_file()


def test_home_brand_files_take_precedence_over_the_package_defaults(tmp_path):
    directory = tmp_path / "brand"
    directory.mkdir()
    (directory / "brand.png").write_bytes(b"png")
    (directory / "brand.ico").write_bytes(b"ico")

    assets = resolve_brand_assets(tmp_path)

    assert assets.png == directory / "brand.png"
    assert assets.ico == directory / "brand.ico"


def test_each_file_falls_back_independently(tmp_path):
    directory = tmp_path / "brand"
    directory.mkdir()
    (directory / "brand.ico").write_bytes(b"ico")

    assets = resolve_brand_assets(tmp_path)

    assert assets.png == PACKAGE_ASSETS / "jarvis.png"
    assert assets.ico == directory / "brand.ico"


def test_a_directory_named_like_an_asset_is_not_an_asset(tmp_path):
    (tmp_path / "brand" / "brand.png").mkdir(parents=True)

    assert resolve_brand_assets(tmp_path).png == PACKAGE_ASSETS / "jarvis.png"


def test_resolution_never_creates_anything(tmp_path):
    resolve_brand_assets(tmp_path)

    assert list(tmp_path.iterdir()) == []
