# Svapo Consapevole

Add-on per Home Assistant: un timer che dà alla sigaretta elettronica il ritmo di una sigaretta vera, con notifiche a pulsanti: tocchi **Inizia** quando finisce la pausa e **Sì, ho finito** quando finisce la sessione, anche dall'Apple Watch.

## Installazione

1. In Home Assistant vai in Impostazioni, Add-on, Store add-on.
2. Dal menu a tre puntini in alto a destra scegli Archivi.
3. Incolla l'URL di questo repository e premi Aggiungi.
4. Cerca **Svapo Consapevole**, installa e avvia.
5. Imposta il telefono per le notifiche seguendo la documentazione dell'add-on.

L'add-on compare nella barra laterale con il nome **Svapo**.

## Contenuto

- `svapo-consapevole/` contiene l'add-on: server Python, pagina web e configurazione.
- `repository.yaml` descrive il repository per il Supervisor.

Il server usa solo la libreria standard di Python, quindi l'immagine resta leggera.
