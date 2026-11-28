# IDEmu – contrato da API HTTP (127.0.0.1, JSON, sem autenticação, só loopback)

Servidor: `python3 -m idemu gui` (padrão http://127.0.0.1:8765). Python 3.9 stdlib apenas.
O front-end (idemu/web/) e o back-end (idemu/server.py) seguem ESTE contrato. Erros: HTTP 4xx/5xx com `{"error":"mensagem em português"}`.
Textos de UI em inglês por padrão, com português do Brasil selecionável (`settings.ui_language`, via POST /api/settings). As mensagens do servidor continuam em português e a GUI as traduz no cliente (idemu/web/i18n.js).

## Estado geral
GET  /api/state -> {"settings":{"psdz_path":"/Users/x/Downloads/psdzdata"|null},
                    "envs":[Env...], "running":"<env id>"|null, "version":"0.1"}
POST /api/settings {"psdz_path":"..."} -> {"ok":true,"psdz_ok":true,"message":"..."}
POST /api/settings {"ui_language":"en"|"pt"} -> {"ok":true}   (idioma da interface; padrão "en", devolvido em /api/state em settings.ui_language)

Env = {"id":"f30-bmw","name":"F30 BMW","created":"2026-11-04T22:00:00",
       "series":"F020","chassis":"F30","brand":"bmw","model_name":"320i",
       "swfl":{"os":"/abs/swfl_0000271a.bin.007_051_002","brand":"/abs/...","hmi":"/abs/..."},
       "coding":{"language":"pt_BR","units":"metric","country":"BR","vin":"WBA...","year":2017,"month":7,"lci":1,
                 "display":"10_25_1440x540","hmi_version":"id6_light","navi":"keine_navi"},
       "net":{"ssh_port":2222,"can_port":29536,"gps_port":29537},
       "build":{"state":"none|building|ready|error","pct":0-100,"step":"texto","error":null|"texto","built_at":null|"iso"}}

## Catálogo (assistente "Novo ambiente")
GET /api/catalog -> {"psdz_ok":true,
  "series":[{"id":"F020","name":"1/2/3/4-Series (F2x/F3x)","chassis":[{"code":"F30","name":"Série 3 (F30/F31/F34)","brand":"bmw","ego_model":"F30"}...]}],
  "roles":[{"role":"os","id":"0000271a","label":"Sistema base (QNX, serviços, drivers)","help":"texto curto",
            "required":true,"files":[{"file":"swfl_0000271a.bin.007_051_002","version":"007_051_002","size":123,"path":"/abs/.."}]},
           {"role":"brand","id":"00002719","label":"Dados da marca BMW", ...}, {"role":"hmi","id":"00002720",...}],
  "by_series":{"F020":{"roles":{"os":"0000271a","brand":{"bmw":"00002719","mini":"00002716","rr":"00002718"},"hmi":"00002720"}}},
  "languages":[{"code":"pt_BR","name":"Português (Brasil)"}...], "countries":[...], "displays":[{"code":"10_25_1440x540","name":"10,25\" 1440x540"}...],
  "hmi_versions":[{"code":"id6_light","name":"iDrive 6 (tiles)"}...]}
(o back-end diz quais arquivos o ambiente precisa; o usuário escolhe um arquivo por papel – lista `files` do papel – ou informa outro caminho.)
A pasta psdzdata é **opcional**: sem ela o catálogo vem da lista interna (`psdz_ok:false`, `files:[]`) e `generations` lista as versões do iDrive (`id6`, `id5` com imagem; `id7`, `id8` com `supported:false`). Cada papel traz `approx_mb`.
POST /api/scan {"path":"/abs/pasta","ids":["0000271a","00002719","00002720"]} -> {"path":"/abs/pasta","files":{"0000271a":[{"file","version","size","path"}...]},"scanned":n,"timeout":false}
     (procura swfl_<id>.bin.<versão> na pasta: raiz do psdzdata, swe/swfl ou qualquer subpasta até 7 níveis; só leitura)
POST /api/pick {"kind":"file"|"folder","prompt":"...","start":"/abs"} -> {"path":"/abs/escolhido"|null}   (seletor nativo do macOS via osascript; null = cancelado; 501 se indisponível, e a GUI usa o seletor interno)
POST /api/settings {"psdz_path":""} -> esquece a pasta psdzdata salva

## Ambientes
POST /api/env/create {name, series, chassis, brand, swfl:{os,brand,hmi}, coding:{...}, net:{...}, home?} -> Env   (`home`: pasta onde a VM fica; o IDEmu cria `<home>/<id>` e liga `environments/<id>` a ela por link simbólico; exige pasta existente, gravável e com 1 GB livre; `Env.home` traz o caminho real. Em `kind` mgu7/mgu22 só os dados e logs vão para lá: a imagem é compartilhada)
GET  /api/env/<id> -> Env
POST /api/env/<id>/update {name?, coding?, net?} -> Env        (coding pode mudar sem rebuild completo)
POST /api/env/<id>/build -> {"ok":true}                         (assíncrono)
GET  /api/env/<id>/build -> {"state":..., "pct":..., "step":..., "log":["linhas recentes"]}
POST /api/env/<id>/start {"cold":false} -> {"ok":true}   (cold=true ignora o estado salvo)        POST /api/env/<id>/stop -> {"ok":true}
POST /api/env/<id>/snapshot/delete -> {"ok":true}   (apaga o estado do boot rápido; Env traz "fast_boot" e "snapshot":{valid,size,enabled}; update aceita fast_boot)
POST /api/env/<id>/delete -> {"ok":true}       POST /api/env/<id>/duplicate {"name":"..."} -> Env

As ações que mudam algo (`update`, `start`, `stop`, `delete`, `duplicate`, `snapshot`, `vin`, `files/*`, `userfiles/reveal`, `vehicle/set`, `most/send`) só aceitam POST. A API recusa (403) pedidos com `Host` que não seja
`127.0.0.1`/`localhost` na porta do servidor, com `Origin` de outro site ou `Sec-Fetch-Site: cross-site` (proteção contra CSRF e DNS rebinding).
No iDrive 5/6, `coding.hu_variant` é o tipo de head unit: `professional` (10,25" 1440×540, navegação, toque), `business` (8,8" 1280×480) ou `entrynav` (6,5" 800×480, sem toque).
O catálogo traz a lista em `hu_variants`; a PSdZData só tem o firmware do NBT Evo, então os três são o mesmo firmware com codificação diferente.

## VIN
GET  /api/vin/decode?vin=<17 caracteres> -> {vin, wmi, maker, type_key, model_year, found, chassis, chassis_name, brand, body, engine, drive, gearbox, steering, market, us,
     generation ("id4".."id8"), series, check_digit_ok, notes:[...], table:{state:"ready|building|error", pct}, env:{generation, series, chassis, brand, name, model_name, coding:{...}}}
     A tabela de tipos (posições 4–7 do VIN) vem da base KIS da PSdZData (`kiswb/<série>/KIS.data`) e fica em `cache/vin_types.json`; na primeira consulta ela é montada em segundo plano
     (`table.state = "building"`, ~15 s) e a resposta repete o pedido mais tarde. O VIN não traz os opcionais do carro: o tipo de head unit continua sendo escolha do usuário.
POST /api/env/<id>/vin {"vin":"...", "hu_variant":"business"?} -> {env, decode, notes:[...]}   (grava o VIN; no iDrive 5/6 também chassi, série, ano, versão do HMI e mercado, se a marca for a mesma)

## Arquivos do sistema
GET  /api/env/<id>/files/status -> {state:"none|extracting|ready|error", pct, step, error, path, files, bytes, source}
POST /api/env/<id>/files/extract -> status   (assíncrono; iDrive 5/6: os três SWFL do ambiente em <env>/system_files/{os,brand,hmi}; iDrive 7: os pacotes HAR em mgu7/system_files/{root,kernel};
     iDrive 8: a raiz montada (mgu22/base.cpio) em mgu22/system_files/root; CIC: o IFS de boot e o EFS_RO em cic/system_files/{IFS,EFS_RO})
GET  /api/env/<id>/files?path=<relativo> -> {path, parent, root, entries:[{name, dir, size, mode, link?}], status}
GET  /api/env/<id>/files/raw?path=<relativo>[&inline=1] -> o arquivo (até 64 MB; HTML, XML, JS e SVG do firmware vão como text/plain)
GET  /api/env/<id>/userfiles -> {dir, mount:"/mnt/EFS_RO", files:[{path,size}], bytes}   (só CIC: o conteúdo de <env>/userfiles/ entra no EFS_RO do guest a cada partida)
POST /api/env/<id>/userfiles/reveal -> {"ok":true}   (cria a pasta e abre no Finder)
GET  /api/vehicle/state -> {signals:{battery_voltage:13.8}, supported:{battery_voltage:{unit:"V",min:6,max:16}}}   (CIC em execução; o resto dos sinais ainda não foi mapeado)
POST /api/vehicle/set {"battery_voltage":13.8} -> state   (tensão da bateria no status da IOC, canal 2; 400 se fora de 6..16 V ou sinal desconhecido)
POST /api/most/send {"hex":"000c07010001000001" "02d801"} -> {"ok":true}   (telegrama MTP/MOST cru para o HMI do CIC; tamanho 0000 é preenchido)
GET  /api/most/seen -> {fblocks:[{fblock,inst,subscribes:[FktID],telegrams:[{fkt,op,n,last}]}]}   (o que o HMI do CIC pediu a outros FBlocks; ver tools/cic/mostscan.py)
POST /api/env/<id>/files/reveal {"path":"..."} -> abre no Finder        POST /api/env/<id>/files/remove -> apaga a pasta extraída
Os caminhos são sempre relativos à pasta extraída: `..`, caminhos absolutos e links simbólicos que saiam dela são recusados.

## Coding
Ao criar um ambiente `kind: "mgu7"`, `role: "hu"`, `POST /api/env/create` aceita `hu_coding_capture`: o conteúdo de uma captura válida de `rawcodingdata` em hexadecimal (4144 bytes antes da conversão). Use uma captura da mesma versão de HMI. O servidor valida a captura antes de criar o ambiente e só grava as diferenças dos campos reconhecidos em `coding.extra`. Um CAFD é a descrição dos parâmetros e um NCD é outro formato de dados. A importação usa a captura de memória do HU. Sem captura, a configuração genérica do IDEmu é usada.

GET  /api/env/<id>/coding -> (iDrive 5/6, 7 e 8; no 7 e no 8 os parâmetros vêm do firmware, `coding.extra` guarda só o que difere da fábrica) {"params":[{name,label,desc,popular,group,bits,max,options:[{value,raw,label}],factory,value,coded}],"groups":[{id,label}],"popular_order":[...],"popular_groups":[...],"backups":[...],"running":bool,"flash":{...}}
POST /api/env/<id>/coding/flash {"changes":{"COMPASS":1,"language":"en_GB","X":null},"note":"..."} | {"reset":true} | {"restore":"<id do backup>"} -> estado do flash (assíncrono; null volta o parâmetro ao padrão)
GET  /api/env/<id>/coding/flash -> {"state":"idle|running|done|error","step":n,"steps":[...],"error":...,"rows":n,"rows_read":n,"verified":bool,"backup":"id","restarted":bool,"warnings":[...]}
POST /api/env/<id>/coding/backup {"note":"..."} -> {"ok":true,"id":"...","backups":[...]}

## Execução (ambiente ligado)
GET  /api/run/status -> {"state":"stopped|booting|running|error","env":"id"|null,"uptime_s":12.3,"boot_step":"texto","boot_pct":0-100,
        "ports":{"ssh":2222,"can":29536,"gps":29537},"frame_seq":123,"fps":4.2,"error":null}
GET /api/run/frame?since=<seq> -> quadro cru (RGB, cabeçalhos X-Frame-Seq/W/H); segura a resposta até haver um quadro novo (204 se não houver em 1,5 s)
GET  /api/run/screen.png          -> PNG do display do carro (1440x540) ; cabeçalho X-Frame-Seq
POST /api/input/key   {"code":1..14,"val":1|0}   códigos: MENU1 BACK2 OPTION3 CD4 RADIO5 TEL6 NAV7 PRESS8 N9 S10 W11 E12 RIGHT13 LEFT14
POST /api/input/rotor {"delta":n}   n>0 horário (envia |n| passos), n<0 anti-horário
POST /api/input/tilt  {"dir":"up|down|left|right"}
POST /api/input/click {"x":0..1439,"y":0..539,"down":true|false,"move":true|false}   toque no display (iDrive 5, 6 e 8); move=true arrasta o dedo já apoiado; ver docs/TOQUE.md
GET  /api/logs?name=console|qemu|renderer|build|guest&tail=200 -> {"lines":[..]}

## Celular (ver docs/CELULAR.md)
GET  /api/phone        -> {"running":bool,"pin":"123456","ips":[..],"http_port":8766,"https_port":8767,"https":bool,"urls":[..],"urls_https":[..],"phones":[ips],"gps_fixes":n,"gps":{lat,lon,speed_kmh,t}|null,"error":""}
POST /api/phone/start  -> mesmo formato; liga o servidor do celular na rede local (PIN novo). 409 se as portas estiverem ocupadas
POST /api/phone/stop   -> mesmo formato
O servidor do celular (portas 8766 HTTP e 8767 HTTPS) é separado e exige o PIN: /login, /p/state, /p/screen.png?since=, /p/input {"t":"rotor|key|tilt|touch",...}, /p/gps {"lat","lon","speed" (m/s),"heading","accuracy"}.

## CAN virtual
GET  /api/can/signals -> {"groups":[{"name":"Motor","signals":[{"name":"vehicle_speed","label":"Velocidade","unit":"km/h","min":0,"max":300,"value":0,"can_id":416,"cycle_ms":20,"step":1,"kind":"number|bool|enum","enum":{"0":"..."}|null}]}], "running":true}
POST /api/can/set {"name":"vehicle_speed","value":80}  -> {"ok":true}
POST /api/can/frame {"id":"1A0","data":"00112233","ext":false} -> {"ok":true}     (injeta quadro bruto)
GET  /api/can/frames?since=<seq>&limit=200 -> {"seq":N,"frames":[{"seq":1,"t":12.345,"id":"1A0","dlc":8,"data":"..","dir":"tx|rx","name":"vehicle_speed"|null}]}
GET  /api/can/scenarios -> {"scenarios":[{"id":"city","name":"Cidade","desc":"..."},...],"active":null|"id"}
POST /api/can/scenario {"id":"city"|null}      (null = parar)
POST /api/can/record {"on":true|false} ; GET /api/can/recordings ; POST /api/can/replay {"file":"x.log","loop":false}

## GPS virtual
GET  /api/gps/state -> {"mode":"static|route|circle|manual","fix":true,"lat":-23.55,"lon":-46.63,"alt":760,"speed_kmh":0,"heading":0,"sats":9,"hdop":0.9,"route":{"name":"x","points":120,"progress":0.35,"length_km":12.1}|null,"sync_can_speed":true,"nmea_tail":["$GPGGA..."]}
POST /api/gps/set {lat?,lon?,alt?,speed_kmh?,heading?,sats?,hdop?,fix?,sync_can_speed?}
POST /api/gps/mode {"mode":"static|route|circle|manual","radius_m":300?}
POST /api/gps/route {"name":"...","gpx":"<xml text>"} | {"name":"...","points":[[lat,lon],...],"speed_kmh":50,"loop":true}
POST /api/gps/jump {"lat":..,"lon":..}

## V850 virtual
GET /api/v850 -> {"connected":true,"tx_msgs":n,"rx_msgs":n,"bytes_from_guest":n,"channels":{"26":{"from_guest":n,"to_guest":n}},"model":{"watchdog":{"heartbeats":n,"cycle_ms":8000,"probes":["SignalHandler"]}},"recent":[{"t":1.2,"dir":"from_guest|to_guest","chan":26,"len":8,"hex":"..."}],"firmware":{"variants":[{"family":"V850","hwindex":"2-3","device":"Headunit C1","appl":"8140_APPL","build":"Jun  8 2017 15:20:16",...}],"ipc_channels":["IpcSGW",...],"gateway_table":{"pages_used":113,"pages":160,...}}}   (409 se o V850 não está ativo; `firmware` = identificação do firmware real do IOC, ver docs/V850_FIRMWARE.md)
GET /api/logs?name=v850 -> log do enlace V850

## Estatísticas avançadas
GET /api/stats?since=<t>&env=<id> -> {"running":bool,"env":"id"|null,"state":"stopped|booting|running","interval":1,"now":t,
   "static":{"host_ram_mb":32768,"cores":10,"gpu":"Apple M1 Max","guest_ram_mb":2048,"qemu_pid":n,"gl_pid":n,"boot_kind":"cold|snapshot"},
   "samples":[{"t":epoch,"up":s,"cpu_qemu":%,"cpu_gl":%,"rss_qemu":MB,"rss_gl":MB,"vsz_qemu":MB,"fps":n,"ft_avg":ms,"ft_p95":ms,"ft_max":ms,"gpu":%,"gpu_render":%,"gpu_tiler":%,"gpu_mem_mb":MB}],
   "storage":{"total":B,"parts":[{"id":"images","label":"...","bytes":B}],"disk_free":B,"disk_total":B},"storage_env":"id"}
   Uma amostra por segundo, histórico de 15 min (zera quando a VM reinicia). `cpu_*` em % de um núcleo (100 = um núcleo cheio). `rss_*` é a RAM residente do processo no Mac;
   o teto é `guest_ram_mb` (opção -m do QEMU). FPS e tempo de quadro vêm do quadro compartilhado do renderizador (só contam quando a tela muda). A GPU é a do Mac inteiro (ioreg): o macOS não separa por processo.

## SSH
GET /api/ssh/info -> {"port":2222,"host":"127.0.0.1","user":"root","key_path":"/abs/id_ed25519","command":"ssh -i ... -p 2222 root@127.0.0.1","state":"up|down","note":"..."}

## Seletor de arquivos no servidor (o navegador não expõe caminhos locais)
GET /api/fs/space?path=/abs/dir -> {"path":"/abs/dir","free":n,"total":n,"writable":true,"default":false}   (espaço livre e permissão de uma pasta; `default` = é a pasta `environments/` do IDEmu)
GET /api/cluster -> {"signals":{"vehicle_speed":0.0,...},"gps":{"fix":true,"speed_kmh":0,"heading":0,"route":{...}|null,"remaining_m":n,"turn":{"dist_m":980,"angle":90,"dir":"left|right|uturn"}|null}|null,"fuel_pct":50.0,"range_km":413,"warnings":[{"id":"door","level":"red|amber|info"}],"hu":[{"dev":"KombiInterface","fkt":512,"name":"CNewCCMessage","op":0,"n":3,"age":1.2,"hex":".."}]}   (cluster e HUD virtuais do iDrive 5 e 6: sinais do CAN, GPS e o que o HMI mandou por MOST ao Kombi 0xE0 e ao HUD 0xE1; 409 sem ambiente iDrive 5/6 em execução; ver docs/CLUSTER_HUD.md)
GET  /api/run/frame?since=N[&fmt=rgba] -> próximo quadro; `fmt=rgba` (iDrive 7) devolve o RGBA do glhost7 sem converter, cabeçalho `X-Frame-Fmt: rgba`
POST /api/guest/run {"cmd":"ls /tmp","timeout":20} -> {"out":"..."}   (depuração, só iDrive 7: roda um comando no shell do guest e devolve a saída)
GET /api/v850/seen?fblock=0xE0 -> {"seen":[{"fblock":224,"inst":0,"fkt":1289,"op":0,"n":3,"age":1.2,"data":".."}]}   (depuração: últimas mensagens Set/Get do HMI por FBlock, instância e função)
GET /api/fs/list?path=/abs/dir -> {"path":"/abs/dir","parent":"/abs","entries":[{"name":"x","dir":true,"size":0}...]} (somente leitura)

POST /api/v850/publish {"fblock":224,"inst":0,"fkt":1289,"data":"0000..."} -> {"ok":true,"delivered":1}   (depuração: envia o Status de uma propriedade MOST ao HMI, se ele a assinou)
POST /api/v850/devices {"devices":[[192,3],[209,0]]} -> {"ok":true,"registered":2}   (depuração: registra mais dispositivos MOST (FBlock, instância) do HMI; o padrão são só Kombi e Vehicle)

## Mapa (ambiente ligado)
GET  /api/map -> {"source":"off|osm|<url com {z}{x}{y}>","online":bool,"zoom":16.0,"headup":false,"night":false,"attribution":"...","sources":["osm"],"cache":"/abs/mapcache","stats":{"requested":n,"downloaded":n,"failed":n,"cached":n},"error":null|"texto"}
POST /api/map {"source"?,"zoom"?,"headup"?,"night"?} -> o mesmo objeto; salvo em settings.json. Padrão: source "off" (nada sai da máquina).
