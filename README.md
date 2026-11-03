# Løpekart

Privat kart over løpeturene mine.

Kartdataene er kryptert (AES-256-GCM, nøkkel avledet med PBKDF2-SHA256), og siden krever passord. Uten passordet inneholder repoet ingen turer, steder eller datoer.

Ekstra vern i tillegg til krypteringen: hver tur kortes av med en tilfeldig lengde i begge ender, og områdene rundt steder der mange turer starter, skjules med tilfeldig størrelse og plassering.
