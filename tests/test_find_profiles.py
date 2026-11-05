import os

import find_profiles


def test_mask_email_hides_everything_but_initials():
    assert find_profiles.mask_email("alice@gmail.com") == "a**@g**.com"
    assert find_profiles.mask_email("bob.smith@mail.example.co.uk") == "b**@m**.example.co.uk"
    assert find_profiles.mask_email("(unnamed)") == "(unnamed)"
    assert find_profiles.mask_email("x@nodot") == "x**@**"


def test_count_bookmarks_all_roots(fixtures):
    assert find_profiles.count_bookmarks(os.path.join(fixtures, "profile_a", "Bookmarks")) == 4
    assert find_profiles.count_bookmarks(os.path.join(fixtures, "profile_b", "Bookmarks")) == 4
    assert find_profiles.count_bookmarks(os.path.join(fixtures, "nope", "Bookmarks")) is None


def test_chromium_profiles_single_and_multi(tmp_path):
    (tmp_path / "Default").mkdir()
    (tmp_path / "Default" / "Bookmarks").write_text("{}")
    (tmp_path / "Profile 2").mkdir()
    (tmp_path / "Profile 2" / "Bookmarks").write_text("{}")
    (tmp_path / "Profile 3").mkdir()  # no Bookmarks -> ignored
    got = list(find_profiles.chromium_profiles(str(tmp_path)))
    assert got == [str(tmp_path / "Default"), str(tmp_path / "Profile 2")]
    single = tmp_path / "opera"
    single.mkdir()
    (single / "Bookmarks").write_text("{}")
    assert list(find_profiles.chromium_profiles(str(single))) == [str(single)]
