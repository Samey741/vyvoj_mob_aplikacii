# project.md – SportNav



## Aký problém riešim

Držitelia Multisport karty nemajú jednoduchý spôsob, ako v reálnom čase nájsť najbližšie akceptované športovisko a okamžite spustiť navigáciu k nemu.

## Kto sú moji useri

Zamestnanci a jednotlivci v SK, CZ, HU a PL, ktorí majú Multisport kartu cez zamestnávateľa a pravidelne hľadajú, kam ísť zacvičiť — najčastejšie na cestách alebo v novom meste. Primárne iOS používatelia, technicky zdatní, zvyknutí na Apple Maps / Google Maps.

## MVP — ako chcem problém vyriešiť

Jedná iOS obrazovka s mapou, ktorá zobrazí piny najbližších Multisport zariadení okolo aktuálnej polohy. Používateľ filtruje podľa kategórie a vzdialenosti, klikne na pin a spustí navigáciu priamo v Apple Maps.

Dátová stratégia: scraper + enricher zbehne raz lokálne (Apify + Apple Maps Server API), výstup sa uloží ako SQLite bundle priamo do aplikácie. Žiadny nasadený backend — všetky dáta sú offline, vyhľadávanie a filter sú lokálne SQL dotazy.

MVP obsahuje:

* Mapa s pinmi (športoviská v okruhu do 10 km, zoradené podľa vzdialenosti)
* Filter: kategória aktivity + prepínač otvorené teraz
* Detail zariadenia: názov, adresa, otváracie hodiny, tlačidlo Navigovať
* Navigácia: odovzdá cieľ do Apple Maps / Google Maps (MKDirections, online)
* ListView: alternatíva k mape pre tých, čo preferujú zoznam
* Lokálna DB: SQLite bundle (\~5 000 zariadení, zbundlovaný v app, žiadny server)

Jedná iOS obrazovka s mapou, ktorá zobrazí piny najbližších Multisport zariadení okolo aktuálnej polohy. Používateľ filtruje podľa kategórie a vzdialenosti, klikne na pin a spustí navigáciu priamo v Apple Maps.

MVP obsahuje:

* Mapa s pinmi (športoviská v okruhu do 10 km, zoradené podľa vzdialenosti)
* Filter: kategória aktivity + prepínač otvorené teraz
* Detail zariadenia: názov, adresa, otváracie hodiny, tlačidlo Navigovať
* Navigácia: odovzdá cieľ do Apple Maps / Google Maps
* ListView: alternatíva k mape pre tých, čo preferujú zoznam
* Backend: jednorazový import \~5 000 zariadení (Apify + Apple Maps enrich), PostgreSQL + PostGIS, REST API

## Non-goals — čo v MVP nebude a prečo

|Funkcia|Prečo nie v MVP|
|-|-|
|Nasadený backend (API server)|Dáta sú SQLite bundle v app; backend treba až keď príde sync obľúbených alebo OTA update dát|
|Autentifikácia / používateľské účty|Vyžaduje Sign in with Apple + backend; pre čítanie lokálnych dát nie je potrebná|
|Obľúbené zariadenia|Závisí na autentifikácii a backu na sync; pridá sa v Beta fáze|
|Push notifikácie|Nie je jasná hodnota v MVP; pridá sa až po validácii use-casov|
|Hodnotenia zariadení|Vyžaduje UGC backend + moderáciu; nie je kľúčové pre navigáciu|
|Apple Watch companion|Príjemný doplnok, nie jadro; fáza 3|
|Skenovanie Multisport karty (kamera/NFC)|Nepomáha s core problémom (nájsť + navigovať)|
|Pokrytie HU a PL|Apify scrape CZ mapu; SK treba overiť trial runom; HU/PL = fáza 3|
|Rokovania s Benefit Systems o API|Nemáme páku bez hotového produktu|

## Technológie

|Vrstva|Technológia|Cena|
|-|-|-|
|iOS jazyk|Swift 5.9+|zadarmo|
|UI|SwiftUI + UIKit (hybridne pre MapKit)|zadarmo|
|Reaktivita|Combine + async/await|zadarmo|
|Mapy a navigácia|MapKit + CoreLocation + MKDirections|zadarmo (iOS SDK)|
|Sieť (iOS)|URLSession + async/await|zadarmo|
|Lokálna DB (v app)|SQLite bundle (Core Data alebo GRDB)|zadarmo|
|Analytics + Crash|Firebase Analytics + Crashlytics|zadarmo (free tier)|
|CI/CD|Xcode Cloud|zadarmo (25 h/mes)|
|Scraper (lokálne, 1x)|Apify Actor janbuchar/multisport-map-scraper|free tier|
|GPS enrich (lokálne, 1x)|Apple Maps Server API|zadarmo (Apple Dev Program $99/rok)|
|GPS fallback (dev only)|Google Places API|zadarmo ($200 kredit)|
|Verzovanie|Git + GitHub|zadarmo|



