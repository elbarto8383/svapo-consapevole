# Svapo Consapevole

Un timer che dà alla sigaretta elettronica il ritmo di una sigaretta vera, per usarla con più consapevolezza. Ti parla con notifiche a pulsanti, anche dall'Apple Watch.

## Come funziona il ciclo

1. **Finisce la pausa**: ti arriva "È ora della sigaretta" con il pulsante **Inizia**. Se non lo tocchi, la sessione non parte. Ti ricordo qualche volta, poi smetto e aspetto.
2. **Tocchi Inizia**: parte la sessione (6 minuti di default, con un tiro ogni 35 secondi). La pagina mostra una sigaretta che si consuma.
3. **Finisce la sessione**: ti arriva "Hai finito?" con il pulsante **Sì, ho finito**. Ti ricordo ogni 3 minuti finché non rispondi.
4. **Tocchi Sì, ho finito**: parte la pausa (45 minuti di default), contata da quando rispondi. Poi si ricomincia da 1.

Se non rispondi a "Hai finito?" per troppo tempo, chiudo io la sessione e faccio partire la pausa.

La pagina dentro Home Assistant mostra le stesse fasi, le statistiche degli ultimi giorni e le impostazioni. Da lì puoi anche iniziare o confermare a mano. Il timer gira nell'add-on, quindi funziona con il telefono bloccato e la pagina chiusa.

## Notifiche e pulsanti

Le notifiche usano l'app companion di Home Assistant e hanno un pulsante.

- **iPhone**: i pulsanti compaiono tenendo premuta la notifica o scorrendola verso il basso.
- **Apple Watch**: i pulsanti funzionano con la Watch App di Home Assistant installata.
- **Android**: i pulsanti sono già visibili sotto la notifica.

I tocchi tornano all'add-on tramite Home Assistant, quindi il telefono deve poterlo raggiungere in quel momento, da casa o con l'accesso remoto.

### Configurazione

1. In Home Assistant apri Strumenti per sviluppatori, Azioni, e cerca `notify.mobile_app`. Trovi un servizio per ogni telefono con l'app companion, ad esempio `notify.mobile_app_il_mio_iphone`.
2. Nelle opzioni dell'add-on inserisci il nome in **Dispositivi per le notifiche**. Va bene con o senza `notify.` davanti.
3. Riavvia l'add-on, apri **Svapo** dalla barra laterale, vai in **Regole** e premi **Prova** nella riga delle notifiche. Tocca il pulsante **Funziona** sulla notifica: la pagina conferma quando il tocco è arrivato. È il modo più rapido per controllare anche il Watch.

La vibrazione dipende dalle impostazioni di suono e vibrazione del telefono e dalla modalità silenziosa. Su iPhone, con `time-sensitive` la notifica supera anche una Modalità Focus, se nelle impostazioni notifiche di Home Assistant è permesso.

### Opzioni

| Opzione | Significato |
| --- | --- |
| `notify_services` | Elenco dei servizi notify da avvisare |
| `reminder_minutes` | Minuti tra un promemoria e l'altro (3) |
| `start_reminders` | Promemoria se non tocchi Inizia (3) |
| `end_reminders` | Promemoria se non rispondi a Hai finito (10) |
| `interruption_level` | `time-sensitive` oppure `active` (solo iPhone) |

## Sicurezza

Svapo si apre solo dentro Home Assistant, dalla barra laterale, ed è protetto dal login di Home Assistant. Non espone nessuna porta di rete, quindi non serve metterlo nel reverse proxy.

## Dati

Sessioni, impostazioni e storico sono salvati in `/data/state.json` dentro l'add-on e restano dopo riavvii e aggiornamenti.
