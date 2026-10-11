# Svapo Consapevole

Un timer che dà alla sigaretta elettronica il ritmo di una sigaretta vera, per usarla con più consapevolezza.

## Come funziona

- **Sessione**: dura quanto imposti (6 minuti di default), con un tiro ogni 35 secondi. La pagina mostra una sigaretta che si consuma e scandisce i tiri con un segnale.
- **Pausa**: a fine sessione parte un conto alla rovescia (45 minuti di default). Quando finisce, è il momento di una nuova sigaretta.
- **Statistiche**: sessioni al giorno, obiettivo giornaliero e sessioni fuori programma.
- **Riduzione graduale**: se attiva, la pausa si allunga di qualche minuto ogni settimana.

I timer girano nell'add-on, quindi le notifiche arrivano anche con il telefono bloccato o la pagina chiusa.

## Notifiche

Arrivano tre notifiche, tramite l'app companion di Home Assistant:

1. all'inizio della sessione
2. alla fine della sessione
3. alla fine della pausa

Non c'è nessuna notifica ai singoli tiri.

### Configurazione

1. In Home Assistant apri Strumenti per sviluppatori, Azioni, e cerca `notify.mobile_app`. Trovi un servizio per ogni telefono con l'app companion, ad esempio `notify.mobile_app_il_mio_iphone`.
2. Nelle opzioni dell'add-on inserisci il nome senza `notify.` in **Dispositivi per le notifiche**, ad esempio `mobile_app_il_mio_iphone`.
3. Riavvia l'add-on, apri **Svapo** dalla barra laterale, vai in **Regole** e premi **Prova** nella riga delle notifiche.

La vibrazione dipende dalle impostazioni di suono e vibrazione del telefono e dalla modalità silenziosa. Su iPhone, con `time-sensitive` la notifica supera anche una Modalità Focus, se nelle impostazioni notifiche di Home Assistant è permesso.

### Opzioni

| Opzione | Significato |
| --- | --- |
| `direct_access` | Consente l'accesso dalla porta di rete, senza ingress |
| `notify_services` | Elenco dei servizi notify da avvisare |
| `notify_start` | Notifica a inizio sessione |
| `notify_end` | Notifica a fine sessione |
| `notify_ready` | Notifica a fine pausa |
| `interruption_level` | `time-sensitive` oppure `active` (solo iPhone) |

## Link a parte e Home dell'iPhone

Oltre che dalla barra laterale, puoi aprire Svapo da un indirizzo tutto suo.

1. Nelle opzioni dell'add-on attiva **Accesso diretto dalla rete**.
2. Nella scheda **Rete** dell'add-on scrivi la porta, per esempio `8099`, e salva.
3. Riavvia l'add-on. Ora risponde su `http://IP-DI-HOME-ASSISTANT:8099`.

L'accesso diretto non ha password: chiunque raggiunga la porta può usare l'app, azzerare lo storico e mandare notifiche di prova. Tienila nella rete di casa. Se la pubblichi con un reverse proxy, proteggila con autenticazione o con un elenco di indirizzi ammessi.

### Metterla nella Home dell'iPhone

1. Apri l'indirizzo in **Safari** (con Chrome su iPhone non compare l'opzione).
2. Tocca **Condividi**, poi **Aggiungi alla schermata Home**.
3. Lascia il nome **Svapo** e conferma.

L'icona si apre a schermo intero, come un'app. Se la apri da fuori casa serve un indirizzo raggiungibile da fuori, ad esempio quello del tuo reverse proxy.

## Dati

Sessioni, impostazioni e storico sono salvati in `/data/state.json` dentro l'add-on e restano dopo riavvii e aggiornamenti.
