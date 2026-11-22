from PIL import Image

from screenshot_manager.quality import is_blank, option_rows
from tests.fake_questions import make_alfaiz_question, make_long_question


def test_blank_and_option_rows():
    assert is_blank(Image.new("RGB", (800, 600), "black"))
    assert is_blank(Image.new("RGB", (800, 600), "white"))
    img, _ = make_alfaiz_question(3, "text")
    assert not is_blank(img) and option_rows(img) == 5
    long = make_long_question(7, 1600)
    assert option_rows(long) == 5
    assert option_rows(long.crop((0, 0, 760, 700))) < 5               # terpotong di tengah pilihan
