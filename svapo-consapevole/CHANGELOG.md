# Registro modifiche

## 0.3.0

- **Notifiche con pulsanti**: a fine pausa ti arriva "È ora della sigaretta" con **Inizia**; se non lo tocchi la sessione non parte. A fine sessione ti arriva "Hai finito?" con **Sì, ho finito**; la pausa parte da quando rispondi.
- **Promemoria**: se non rispondi ti ricordo ogni 3 minuti. Dopo 3 promemoria senza **Inizia** smetto e aspetto. Dopo 10 senza **Sì, ho finito** chiudo io la sessione e parte la pausa.
- **Funziona dal Watch**: i pulsanti compaiono anche sull'Apple Watch con la Watch App di Home Assistant installata.
- Nelle Regole il tasto **Prova** manda una notifica con il pulsante **Funziona** e conferma quando il tocco è arrivato, così controlli tutto il giro.
- **Più sicuro**: tolto l'accesso diretto dalla rete (porta 8099, opzione `direct_access`, icona per la Home). Svapo si apre solo dalla barra laterale di Home Assistant, protetto dal suo login.
- Tolte le opzioni `notify_start`, `notify_end` e `notify_ready`, sostituite dai pulsanti. Nuove opzioni: `reminder_minutes`, `start_reminders`, `end_reminders`.
- Il tasto **Termina qui** durante la sessione fa partire subito la pausa, senza chiedere conferma.

## 0.2.2

- Nelle Regole la riga **Vibrazione** ora dice chiaramente quando il dispositivo non la supporta, come su iPhone: l'interruttore si disattiva e il tasto Prova sparisce. Su iPhone il telefono vibra con le notifiche di Home Assistant.

## 0.2.1

- Corretto l'errore "Missing option 'direct_access'" che impediva di salvare le opzioni dopo l'aggiornamento alla 0.2.0. L'opzione ora è facoltativa.

## 0.2.0

- **Link a parte**: Svapo si può aprire anche da un indirizzo tutto suo (`http://IP-DI-HOME-ASSISTANT:8099`), senza passare dalla barra laterale. Si attiva con l'opzione **Accesso diretto dalla rete** e impostando la porta nella scheda **Rete**.
- **Home dell'iPhone**: la pagina si può aggiungere alla schermata Home da Safari e si apre a schermo intero, con la sua icona.
- Aggiunti icona e logo dell'add-on.
- Nuova opzione `direct_access`, spenta di default. L'accesso diretto non ha password: usalo nella rete di casa o dietro un reverse proxy protetto.

## 0.1.0

- Prima versione.
- Sessione a ritmo di sigaretta vera: durata e ritmo dei tiri a scelta, con sigaretta che si consuma.
- Pausa tra una sessione e l'altra, con conto alla rovescia e pulsante "Ho ceduto".
- Notifiche sul telefono a inizio sessione, fine sessione e fine pausa, anche con il telefono bloccato.
- Statistiche degli ultimi 7 giorni, obiettivo giornaliero e riduzione graduale della pausa.
- Sessioni e impostazioni salvate nell'add-on, uguali su tutti i dispositivi.
