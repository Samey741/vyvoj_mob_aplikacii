# project.md – SportNav



## Aký problém riešim

Držitelia Multisport karty nemajú jednoduchý spôsob, ako v reálnom čase nájsť najbližšie akceptované športovisko a okamžite spustiť navigáciu k nemu.

## Kto sú moji useri

Zamestnanci a jednotlivci v SK, CZ, HU a PL, ktorí majú Multisport kartu cez zamestnávateľa a pravidelne hľadajú, kam ísť zacvičiť — najčastejšie na cestách alebo v novom meste. Primárne používatelia Android telefónov, technicky zdatní, zvyknutí na Google Maps / Waze.

## MVP — ako chcem problém vyriešiť

Jedná Android obrazovka s mapou, ktorá zobrazí piny najbližších Multisport zariadení okolo aktuálnej polohy. Používateľ filtruje podľa kategórie a vzdialenosti, klikne na pin a spustí navigáciu priamo v Google Maps (alebo Waze či inej nainštalovanej mapovej aplikácii).

Dátová stratégia: scraper + enricher zbehne raz lokálne (Apify + OpenStreetMap Nominatim), výstup sa uloží ako SQLite databáza priamo do aplikácie. Žiadny nasadený backend — všetky dáta o zariadeniach sú offline, vyhľadávanie a filter sú lokálne. Celé riešenie je bez nákladov (žiadne platené služby, API kľúče ani platobné karty).

MVP obsahuje:

* Mapa s pinmi (športoviská v okruhu do 10 km, zoradené podľa vzdialenosti)
* Filter: kategória aktivity + prepínač otvorené teraz
* Detail zariadenia: názov, adresa, otváracie hodiny, tlačidlo Navigovať
* Navigácia: odovzdá cieľ do Google Maps / Waze / inej mapovej aplikácie (Android Intent, online)
* ListView: alternatíva k mape pre tých, čo preferujú zoznam
* Lokálna DB: SQLite databáza (\~5 000 zariadení, zabudovaná v aplikácii, žiadny server)

Jedná Android obrazovka s mapou, ktorá zobrazí piny najbližších Multisport zariadení okolo aktuálnej polohy. Používateľ filtruje podľa kategórie a vzdialenosti, klikne na pin a spustí navigáciu priamo v Google Maps (alebo Waze či inej nainštalovanej mapovej aplikácii).

MVP obsahuje:

* Mapa s pinmi (športoviská v okruhu do 10 km, zoradené podľa vzdialenosti)
* Filter: kategória aktivity + prepínač otvorené teraz
* Detail zariadenia: názov, adresa, otváracie hodiny, tlačidlo Navigovať
* Navigácia: odovzdá cieľ do Google Maps / Waze / inej mapovej aplikácie
* ListView: alternatíva k mape pre tých, čo preferujú zoznam
* Backend: jednorazový import \~5 000 zariadení (Apify + Nominatim enrich), PostgreSQL + PostGIS, REST API

## Non-goals — čo v MVP nebude a prečo

|Funkcia|Prečo nie v MVP|
|-|-|
|Nasadený backend (API server)|Dáta sú SQLite bundle v app; backend treba až keď príde sync obľúbených alebo OTA update dát|
|Autentifikácia / používateľské účty|Vyžaduje prihlasovanie (napr. Google účet) + backend; pre čítanie lokálnych dát nie je potrebná|
|Obľúbené zariadenia|Závisí na autentifikácii a backu na sync; pridá sa v Beta fáze|
|Push notifikácie|Nie je jasná hodnota v MVP; pridá sa až po validácii use-casov|
|Hodnotenia zariadení|Vyžaduje UGC backend + moderáciu; nie je kľúčové pre navigáciu|
|Wear OS companion (hodinky)|Príjemný doplnok, nie jadro; fáza 3|
|iOS verzia|Vývoj a testovanie vyžadujú Mac s Xcode; publikácia platený Apple Developer Program; fáza 3|
|Publikácia v Google Play|Jednorazový registračný poplatok; MVP sa inštaluje ako APK|
|Skenovanie Multisport karty (kamera/NFC)|Nepomáha s core problémom (nájsť + navigovať)|
|Pokrytie HU a PL|Apify scrape CZ mapu; SK treba overiť trial runom; HU/PL = fáza 3|
|Rokovania s Benefit Systems o API|Nemáme páku bez hotového produktu|

## Technológie

|Vrstva|Technológia|Cena|
|-|-|-|
|Platforma|Android 8.0+ (API 26)|zadarmo|
|Jazyk|Kotlin|zadarmo|
|UI|Jetpack Compose + Material 3|zadarmo|
|Reaktivita|Kotlin coroutines + StateFlow|zadarmo|
|Mapy|MapLibre Native Android + dlaždice OpenFreeMap|zadarmo (bez kľúča a registrácie)|
|Poloha|Android LocationManager (bez Google Play Services)|zadarmo|
|Navigácia (externá)|Android Intent → Google Maps / Waze / `geo:`|zadarmo|
|Sieť|iba mapové dlaždice (MapLibre); dáta o zariadeniach offline|zadarmo|
|Lokálna DB (v app)|SQLite databáza v assets (Android SQLiteDatabase)|zadarmo|
|Analytics + Crash|Firebase Analytics + Crashlytics|zadarmo (free tier)|
|Vývojové prostredie|Android Studio + Gradle (beží na Windows)|zadarmo|
|CI/CD|žiadne — testy lokálne cez Gradle|zadarmo|
|Scraper (lokálne, 1x)|Apify Actor janbuchar/multisport-map-scraper|free tier (5 $ kredit / mesiac)|
|GPS enrich (lokálne, 1x)|OpenStreetMap Nominatim|zadarmo (bez kľúča, max. 1 požiadavka/s)|
|Verzovanie|Git + GitHub|zadarmo|



