"""Small evidence-backed candidate pack, NOT a universal water-quality guarantee.

Checked 2026-10-01. Upper catalogue flows are rejection ceilings only: the
cartridge and UV water-quality rating still need a supplier selection sheet.
No guessed head-loss curve, UV dose, contaminant limits or lifetime is stored.
"""

PACK_ID = "residential_terrace_irrigation"
PACK_LABEL = "Жилая терраса → полив озеленения"
CATALOG = (
    {
        "id": "geizer-jumbo-20-pp5", "name": "Фильтр механической очистки",
        "model": "Гейзер Джамбо 20 с PP 5–20BB", "manufacturer": "Гейзер",
        "article": "32034", "connection": '1", внутренняя резьба',
        "size_mm": "570 × 185", "temperature_min_c": 4, "temperature_max_c": 40,
        "screening_flow_max_m3h": 2.4, "head_loss_m": None,
        # The document says «7 атм» without distinguishing at/atm. Use the
        # lower conversion for a conservative screen, not a passport PN claim.
        "pressure_screen_bar": 7 * 0.980665,
        "pressure_note": "До 7 атм; для предварительной проверки консервативно 6,86 бар. Уточнить единицу и допустимое давление у изготовителя.",
        "rating_note": "До 40 л/мин для корпуса; рабочий расход зависит от картриджа. 5 мкм не гарантируют качество перед УФ.",
        "included": "Картридж PP 5–20BB, корпус, крышка, кронштейн и монтажный комплект входят в арт. 32034; отдельно не дублировать.",
        "source": "https://shop.geizer.com/catalog/gotovye_resheniya/geyzer_dzhambo_20/",
        "manual": "https://shop.geizer.com/upload/iblock/df7/Geyzer-Dzhambo-_-instruktsiya.pdf",
        "manual_sha256": "05f2f842dd7e0866744e9f23a4217e47663eecf3ae94170d048bd3ac1a0a0142",
    },
    {
        "id": "lit-duv-1-48-n-mst", "name": "Установка УФ-обеззараживания",
        "model": "ЛЕНА DUV-1-48-N MST", "manufacturer": "НПО ЛИТ",
        "article": "", "connection": '1", резьбовое', "size_mm": None,
        "temperature_min_c": None, "temperature_max_c": None,
        "screening_flow_max_m3h": 3.2, "head_loss_m": None,
        "pressure_screen_bar": 16, "pressure_note": "Рабочее давление до 16 бар.",
        "rating_note": "Каталог: 0,4–3,2 м³/ч в зависимости от воды. Это диапазон производительности для разных условий, НЕ диапазон допустимого рабочего протока.",
        "included": "УФ-датчик, блок химической промывки и пробоотборники входят в установку; отдельно не дублировать.",
        "power_w": 52,
        "source": "https://lit-uv.ru/catalog/products/obrabotka-vody/lena/duv-1-48-n-mst/",
        "manual": None,
    },
)
