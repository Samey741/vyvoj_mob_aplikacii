# frontend – iOS aplikácia SportNav

Natívna iOS 16+ aplikácia (Swift 5.9+, SwiftUI, MapKit, CoreLocation), viď [DESIGN.md](../DESIGN.md), sekcie 4–6.

- Architektúra MVVM: View (SwiftUI) → ViewModel → Repository (SQLite reader + CoreLocation)
- Lokálna DB: `venues.sqlite` z `backend/` zabudovaná v app bundle (`SQLite.swift`)
- Obrazovky: Mapa (Home), Filter sheet, Karta zariadenia
- Externá navigácia cez deep linky (`maps://`, `comgooglemaps://`)
