# Løpekart

Kart over løpeturene mine fra Strava, med Kartverket-kart, satellitt og OpenStreetMap.

- `index.html` er selve kartet. Det bygges på nytt hver natt fra Strava.
- `build/build.py` bygger kartet fra Strava-svar (`list_activities` med `include_polyline`).
- `build/korreksjoner.csv` retter turer der klokka døde eller GPS-en sviktet, og fjerner feilopptak.

**Personvern:** Sporene klippes innenfor 500 m fra steder der minst tre turer starter eller slutter, slik at hjemmet ikke vises. Siden ber søkemotorer om ikke å indeksere den.

Lenke til én tur: `…/lopekart/#<strava-aktivitets-id>`
