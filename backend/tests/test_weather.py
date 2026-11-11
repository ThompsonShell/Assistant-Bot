from app.integrations.weather import Weather, clothing_advice


def _w(temp, feels=None, wind=0.0, code=0):
    return Weather(city="Toshkent", temp=temp, feels_like=feels if feels is not None else temp, wind=wind, code=code)


def test_clothing_advice_scales_with_temperature():
    assert "issiq" in clothing_advice(_w(34)).lower()
    assert "futbolka" in clothing_advice(_w(25)).lower()
    assert "kofta" in clothing_advice(_w(18)).lower()
    assert "kurtka" in clothing_advice(_w(10)).lower()
    assert "sharf" in clothing_advice(_w(3)).lower()
    assert "palto" in clothing_advice(_w(-5)).lower()


def test_clothing_advice_uses_feels_like_not_actual():
    # Hot air but windy "feels" cold -> advice follows the feels-like value.
    assert "palto" in clothing_advice(_w(2, feels=-4)).lower()


def test_clothing_advice_flags_rain_snow_wind():
    assert "soyabon" in clothing_advice(_w(15, code=63)).lower()      # rain
    assert "qor" in clothing_advice(_w(-1, code=73)).lower()          # snow
    assert "shamol" in clothing_advice(_w(12, wind=40)).lower()       # strong wind


def test_weather_properties():
    w = _w(20, code=61)  # light rain
    assert w.is_rain and not w.is_snow
    assert w.emoji and w.description
    assert _w(20, code=75).is_snow  # heavy snow
