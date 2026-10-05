# Установка и запуск

## Требования

- Python 3.10+ с `pip` и `venv`.
- Интернет для установки Python-пакетов; с `--layout` также для загрузки ELK.
- Распакованный ZIP репозитория или локальный клон.

Основной проверяемый сценарий готовых схем: Windows 10/11. Установщик также
использует стандартные пути Linux/macOS, но эти ОС пока не проверяются в CI.
При переносе готовых координат учитывайте различия шрифтов, описанные ниже.

## Установка одной командой

Откройте терминал в папке с `install.py` и `pyproject.toml`:

```powershell
python --version
python install.py
```

Если `python` не найден, попробуйте `py -3 install.py` либо установите Python
и включите его добавление в PATH.

Установщик создаёт `.venv`, устанавливает туда проект в режиме editable и
Pillow/PyYAML, проверяет импорт и разбор примера. Он не удаляет исходники схем, не меняет
глобальный Python, не требует администратора и не изменяет настройки оболочки.
Повторный запуск допустим. Не переносите `.venv` между компьютерами: создавайте
окружение заново на каждой машине.

## Дополнительные режимы

```powershell
python install.py --layout
python install.py --dev
python install.py --layout --dev
```

- `--layout`: локальный Node.js через `nodejs-wheel`, ELK через
  `npm ci --ignore-scripts` по `package-lock.json` и проверка трассировки.
  Команда npm ci пересоздаёт каталог зависимостей `node_modules`.
- `--dev`: дополнительно pytest.
- Без `--layout` доступны PNG/SVG и все подготовленные YAML с маршрутами.
- ELK нужен только для новой автоматической компоновки и больших генераторов.

При ошибке возвращается ненулевой код. Проверьте сообщение, подключение к сети
и повторите установку. Проверка сертификатов не отключается.

## Запуск

Активация окружения не требуется:

```powershell
.venv\Scripts\python.exe -m schematic_renderer examples/simple.yaml -o output/simple.png
.venv\Scripts\python.exe -m schematic_renderer examples/fixed15_functional/fixed15_functional.yaml -o output/fixed15.png
.venv\Scripts\python.exe -m schematic_renderer examples/float15_functional/float15_functional.yaml -o output/float15.svg
```

Рендерер создаёт каталог результата автоматически. `output` предназначен только
для результатов и исключён из Git. Храните редактируемые исходники в `examples`
или собственном каталоге, а не в `output`.

Для необязательной активации выполните `.venv\Scripts\Activate.ps1`.
После неё доступны `python -m schematic_renderer` и `schematic-renderer`.
Если политика PowerShell блокирует активацию, используйте полный путь к Python,
как выше: менять политику не нужно.

## Linux / macOS и шрифты

```bash
python3 install.py
.venv/bin/python -m schematic_renderer examples/simple.yaml -o output/simple.png
```

В некоторых Linux-дистрибутивах компонент `venv` устанавливается отдельно
через пакетный менеджер ОС. Для ELK добавьте `--layout`.

Рендерер выбирает доступный шрифт: DejaVu Sans, Arial, затем Segoe UI Symbol;
при отсутствии использует запасной шрифт Pillow. Готовые функциональные YAML
размещались с Arial. Другой шрифт может увеличить блоки и нарушить уже сохранённые
маршруты. Для идентичного рисунка нужна та же метрика шрифта. Иначе выполните
новую компоновку `.logic.yaml` в своей среде и добавьте внешние стрелки по новым
координатам. Шрифты Windows в репозитории не распространяются.

## Ручная установка

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[test,layout]"
.venv\Scripts\python.exe -c "from nodejs_wheel import npm; raise SystemExit(npm(['ci', '--ignore-scripts']))"
```

Для обычного рендера достаточно `pip install -e .`, без дополнительных групп
и команды npm. Системные Node.js/npm тоже подходят: выполните `npm ci --ignore-scripts`
из корня проекта. Модуль подготовки сначала ищет `node` в PATH, затем в `nodejs-wheel`.

## Частые ошибки

| Ошибка | Решение |
| --- | --- |
| `No module named ...` | Запускайте Python из `.venv`, а не другой интерпретатор. |
| `.venv exists but is not a virtual environment` | Самостоятельно переименуйте конфликтующий каталог; установщик его не удаляет. |
| Ошибка `venv` / `ensurepip` | Установите полную версию Python или компонент venv для своей ОС. |
| `Cannot find module elkjs` | Выполните `python install.py --layout`. |
| PNG не перезаписывается / `Invalid argument` | Закройте удерживающий файл просмотрщик либо задайте другое имя результата. |
| Провода пересекают блоки после переноса | Проверьте метрики шрифтов и пересчитайте компоновку. |
| Маленькие элементы | Увеличьте `canvas.scale` или используйте SVG; не уменьшайте блоки ради листа. |
| `Unknown pin` / `Unknown block` | В связях нужны ID, а не визуальные подписи `label`. |

Подробнее: [формат YAML](yaml-format.md).
