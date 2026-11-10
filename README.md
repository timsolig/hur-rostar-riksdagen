# Vem röstar med vem

Statisk sida som visar hur riksdagens partier röstar i voteringar och hur ofta de röstar lika.

Tre vyer:

* **Voteringar.** Riksmöten till vänster, voteringar i mitten. Hovra för att se kammaren och mandaten per parti, klicka för att låsa.
* **Samarbete.** Matris med andel lika röster för varje partipar, avgränsad på riksmöten.
* **Egen majoritet.** Välj partier och se mandat, hur ofta de röstat lika per riksmöte, vilka par som drar isär och var de röstat olika.

## Köra lokalt

```sh
python build_data.py          # första gången hämtas alla riksmöten från 2002/03
python -m http.server
```

Öppna http://localhost:8000. Sidan läser `data/` med fetch, så den måste serveras över http.

Senare körningar uppdaterar bara innevarande och föregående riksmöte. `--all` hämtar om allt, `--rm 2019/20` ett enskilt riksmöte. Skriptet använder bara standardbiblioteket.

## GitHub Pages

1. Lägg repot på GitHub.
2. Settings, Pages, Source: **GitHub Actions**.
3. Workflowen hämtar data varje natt, sparar den i `data/` och publicerar sidan. Den körs också vid push och kan startas för hand under Actions.

## Så räknas det

Ett partis linje i en votering är det alternativ (ja, nej eller avstår) som flest av partiets närvarande ledamöter valde. Två partier är överens när deras linjer är samma. Frånvarande räknas inte, och oavgjort inom ett parti gör att voteringen inte räknas för det partiet.

Bara huvudvoteringar finns med. Omröstningar som inte hör till ett betänkande, till exempel statsministeromröstningar och misstroendeförklaringar, är med och får titel och datum från voteringens eget dokument. Beslut utan omröstning syns inte, så den verkliga samsynen är större än siffrorna. Folkpartiet räknas som Liberalerna.

Källa: Sveriges riksdag, [data.riksdagen.se](https://data.riksdagen.se).
