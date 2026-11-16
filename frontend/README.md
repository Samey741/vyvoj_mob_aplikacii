# frontend – Android aplikácia SportNav

Natívna Android aplikácia (Android 8.0+ / API 26, Kotlin, Jetpack Compose, MapLibre + OpenFreeMap), viď [DESIGN.md](../DESIGN.md), sekcie 4–6 a 9.2.

- Architektúra MVVM: UI (Jetpack Compose) → ViewModel (StateFlow) → Repository (SQLite reader) + LocationService
- Lokálna DB: `venues.sqlite` z `backend/` zabudovaná v `app/src/main/assets/` (offline, žiadny server)
- Mapa: MapLibre Native s dlaždicami OpenFreeMap — zadarmo, bez API kľúča (iba dlaždice vyžadujú internet)
- Obrazovky: Mapa (Home), Filter sheet, Karta zariadenia
- Externá navigácia cez Android Intent (Google Maps, Waze, `geo:`)

Gradle projekt vytvára človek v Android Studio (DESIGN.md §10, krok 4). Testy: `./gradlew testDebugUnitTest`.
