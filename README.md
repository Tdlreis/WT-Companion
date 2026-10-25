# WT Companion

Painel que roda no seu PC enquanto você joga War Thunder (batalhas aéreas). Ele descobre
qual avião inimigo você está enfrentando, compara com o seu e diz como atacar.

## Como usar

1. Dê dois cliques em **`iniciar.bat`**. O painel abre no navegador em http://localhost:8191.
2. Entre numa batalha. Deixe o painel num segundo monitor, no celular (`iniciar_celular.bat`)
   ou dê Alt+Tab quando morrer/respawnar. Para alternar rápido, use o jogo em "janela sem bordas".
3. Se trocar de apelido no jogo, ajuste o nick em **Configuração**, no fim da página.

### Como ele sabe qual é o inimigo

O mapa do jogo mostra onde cada avião está e para onde aponta, mas não diz quem é. O kill feed
diz quem acertou quem, mas não diz onde. O painel liga os dois: guarda os últimos segundos do
mapa e, quando o kill feed fala de alguém, olha quem estava na posição certa naquela hora.

| Situação | O que aparece |
|---|---|
| Você **trava um alvo** | Classe (caça, bombardeiro ou ataque), distância, direção em "horas" e se ele está vindo na sua direção |
| Você **atira e acerta** ("Tdlreis set afire X") | O nome vai para o inimigo que estava na frente do seu nariz, ao alcance das armas, enquanto o gatilho estava apertado. Aparece como **certo** |
| Alguém te acerta | O nome vai para o inimigo daquela classe que estava apontando para você |
| Um aliado troca tiros com um inimigo, ou derruba/é derrubado | O app reconhece pela posição dos dois e guarda o nome; quando você trava esse inimigo depois, ele já aparece (como **provável**) |
| Um aliado (ou você, com a tecla de rádio abaixo) marca um inimigo no rádio ("Attack X!") | O inimigo marcado pisca no mapa do jogo e o nome vai para ele na hora |
| Alguém te derruba | Enquanto você espera o respawn: quem foi e como vencer aquele avião |
| Você derruba alguém | Um aviso rápido "Você derrubou X" e o painel limpa e vai para o próximo alvo |
| Você clica num inimigo da lista ou busca um avião | A comparação que você quiser (volta ao automático sozinho quando você cai ou nasce de novo) |

Quando não há pista suficiente, o painel **não chuta**: mostra a classe do alvo e a lista de
inimigos daquela classe que já apareceram no kill feed.

### Atalho opcional: tecla de rádio

O painel funciona sem isso, mas quando você quer o modelo do alvo **antes** de trocar tiros,
dá para usar uma mensagem de rádio ligada a uma tecla (recurso normal do War Thunder):

1. Abra **Controls** e procure por *radio message*.
2. Em **Favorite radio message 1**, escolha **"Attack [alvo]!"** (ou "I'm attacking [alvo]!").
3. Ligue **Quick radio message #1** a uma tecla fácil (um botão lateral do mouse, por exemplo).
4. Na batalha: trave o alvo e aperte a tecla **uma vez**. O alvo pisca no mapa do time e o
   painel mostra o avião exato (como **certo**).

Use com moderação: repetir a mensagem em sequência dá bloqueio de chat por spam, e as regras do
jogo falam em "abuso de comandos de rádio". Uma vez por alvo basta; para o resto, o kill feed e o
mapa resolvem sozinhos.

### Radar

No canto do painel fica um radar com você no centro, apontando para cima, e os aviões em volta
(laranja = inimigo, azul = aliado; triângulo = caça, quadrado = bombardeiro, losango = ataque).
O seu alvo ganha um anel, e quem estiver colado atrás de você pisca em vermelho. Inimigos já
reconhecidos mostram o nome. Clique num deles para comparar. Dá para trocar o alcance entre
2, 4 e 8 km.

É o mesmo dado do mapa que o jogo oferece no navegador. Use o painel no **celular ou no segundo
monitor**, não por cima do jogo: a Gaijin considera "ESP" um overlay na tela do jogo que marca
inimigos em volta.

A comparação mostra velocidade, subida, curva, rolagem, limite de mergulho, teto,
potência/peso, armamento e artilheiros, além de um **plano de ataque** com dicas.

## É seguro? (ban)

Sim. O painel usa **só** a página web oficial que o próprio jogo abre em
`http://localhost:8111`, a mesma do mapa no navegador/celular que a Gaijin oferece.
Ele **não** lê a memória do jogo, não injeta nada, não manda nada no chat, não aperta teclas,
não desenha sobre a tela do jogo e não altera nenhum arquivo do War Thunder. Os dados dos aviões
vêm do datamine público no GitHub.

## Limitações

- O jogo não informa o modelo nem a altitude dos inimigos no mapa. O app segue cada avião
  no mapa e dá nome a ele só quando o kill feed e a posição deixam claro quem é. Em briga
  embolada ele prefere não chutar.
- O kill feed só fala de dano **grave** ("severely/critically damaged", "set afire") e de
  abates. Tiros leves não aparecem, então o nome pode demorar alguns tiros para chegar.
- O mapa é plano (sem altitude): um inimigo bem acima ou abaixo de você pode parecer "na frente".
  Por isso o tiro só conta se o gatilho estava apertado e se ele era o único naquela direção.
- A altitude dos inimigos só aparece quando um aviso de rádio de **aliado** informa
  ("[E4, alt. 1500 m]"). Os seus próprios avisos não trouxeram altitude nos testes.
- Os números são da ficha do jogo. No arcade os valores absolutos mudam, mas a diferença
  entre os dois aviões continua valendo.
- O reconhecimento de frases do kill feed foi feito para o jogo em **inglês**.

## Manutenção

- Depois de um patch grande, rode **`atualizar_banco.bat`** para atualizar BRs e aviões novos.
- `data/cache` guarda os downloads para a atualização ser rápida; pode apagar se quiser espaço.
- Precisa de Python 3 (já instalado neste PC).
