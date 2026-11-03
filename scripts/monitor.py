
name: PokeStock V8.1 Nationwide Monitor

on:
  workflow_dispatch:
  schedule:
    - cron: "17 */2 * * *"

permissions:
  contents: write

concurrency:
  group: pokestock-v81-monitor
  cancel-in-progress: false

jobs:
  monitor:
    name: Catalogue and Nationwide Store Discovery
    runs-on: ubuntu-latest
    timeout-minutes: 20

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          ref: main
          persist-credentials: true

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          python -m pip install requests beautifulsoup4

      - name: Validate Python scripts
        run: |
          python -m py_compile scripts/monitor.py
          python -m py_compile scripts/discover_stores.py

      - name: Validate existing catalogue
        run: |
          python - <<'PY'
          import json
          from pathlib import Path

          path = Path("data/status.json")

          if not path.exists():
              raise SystemExit("Existing catalogue missing")

          data = json.loads(path.read_text(encoding="utf-8"))

          if not isinstance(data.get("products"), list):
              raise SystemExit("Invalid products catalogue")

          if not isinstance(data.get("releases"), list):
              raise SystemExit("Invalid releases catalogue")

          print("Existing products:", len(data["products"]))
          print("Existing releases:", len(data["releases"]))
          PY

      - name: Run nationwide store discovery
        run: |
          python scripts/discover_stores.py

      - name: Run V8 catalogue and inventory monitor
        run: |
          python scripts/monitor.py

      - name: Validate generated JSON
        run: |
          python - <<'PY'
          import json
          from pathlib import Path

          required = [
              "data/status.json",
              "data/stores.json",
              "data/shipments.json",
              "data/discovery_state.json"
          ]

          for filename in required:
              path = Path(filename)

              if not path.exists():
                  raise SystemExit(
                      f"Missing generated file: {filename}"
                  )

              with path.open(encoding="utf-8") as file:
                  json.load(file)

              print("VALID:", filename)

          status = json.loads(
              Path("data/status.json").read_text(
                  encoding="utf-8"
              )
          )

          stores = json.loads(
              Path("data/stores.json").read_text(
                  encoding="utf-8"
              )
          )

          if not status.get(
              "monitor_version", ""
          ).startswith("8"):
              raise SystemExit("V8 monitor version missing")

          if not isinstance(stores, list):
              raise SystemExit("Invalid store directory")

          print("Products:", len(status["products"]))
          print("Stores:", len(stores))
          PY

      - name: Commit updated data
        run: |
          git config user.name "pokestock-bot"
          git config user.email "actions@users.noreply.github.com"

          git add \
            data/status.json \
            data/stores.json \
            data/shipments.json \
            data/discovery_state.json

          if git diff --cached --quiet; then
            echo "No new data to publish."
          else
            git commit -m "Update PokeStock V8.1 nationwide data"
            git push origin HEAD:main
          fi

      - name: Display discovery results
        run: |
          python - <<'PY'
          import json
          from pathlib import Path

          status = json.loads(
              Path("data/status.json").read_text(
                  encoding="utf-8"
              )
          )

          state = json.loads(
              Path("data/discovery_state.json").read_text(
                  encoding="utf-8"
              )
          )

          print("=== POKESTOCK V8.1 ===")
          print(
              "Catalogue products:",
              len(status.get("products", []))
          )
          print(
              "Last region:",
              state.get("last_region")
          )
          print(
              "New stores:",
              state.get("last_new_stores", 0)
          )
          print(
              "Total mapped stores:",
              state.get("total_stores", 0)
          )
          print(
              "Last discovery error:",
              state.get("last_error")
          )
          PY
