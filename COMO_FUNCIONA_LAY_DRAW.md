# Como funciona a estratégia Lay Draw (O empate)

## Ideia em uma frase
Você **aposta contra o empate** no início do jogo. Se alguém marcar gol, a odd do empate sobe e o bot **fecha a posição com lucro**. Se não sair gol e a odd cair, o bot **fecha com perda controlada** ou no intervalo.

---

## Passo a passo

### 1. Entrada (LAY no empate)
- O bot só entra nos **primeiros 15 minutos**, quando a odd do empate está entre **2,8 e 3,5**.
- Ele faz **LAY no empate** = está “contra” o empate.
  - **Se o jogo NÃO terminar empatado** → você ganha o valor apostado (stake).
  - **Se terminar empatado** → você perde: stake × (odd − 1).

Exemplo: LAY R$ 2,62 @ 2,90 no empate  
- Ganha R$ 2,62 se não empatar.  
- Perde 2,62 × (2,90 − 1) ≈ R$ 4,98 se empatar.

### 2. Saída (fechar com BACK no empate)
O bot **não espera o apito final**. Ele fecha a posição colocando **BACK no empate** na odd atual. Assim fica “hedgeado”: o resultado do jogo não importa mais, o lucro/perda já está definido.

- **Take profit:** se a odd do empate subir para **≥ 4,5** (ex.: saiu gol) → fecha com BACK → **lucro**.
- **Stop loss:** se a odd cair para **≤ 2,2** (jogo travado, empate mais provável) → fecha com BACK → **perda limitada**.
- **Timeout:** se chegar aos **45 min** sem nenhum gatilho → fecha → sai no zero ou perda pequena.

### 3. O que apareceu no seu extrato (Al Ahli Amman x Shabab Al Ordon)
- **Contra (LAY)** @ 2,90, R$ 2,62 → **Ganhas R$ 2,62**  
  → Foi a aposta inicial: você “vendeu” o empate.
- **A favor (BACK)** @ 2,22, R$ 3,45 → **Perdidas R$ 3,45**  
  → Foi o fechamento: o bot comprou empate para sair da posição (provavelmente stop loss ou timeout).  
  **Resultado líquido nesse jogo:** +2,62 − 3,45 = **−0,83** (pequena perda ao fechar).

---

## Resumo
| Ação        | O que é                          |
|------------|-----------------------------------|
| LAY empate | Apostar que o jogo **não** termina empatado |
| Fechar     | Fazer BACK no empate para travar P&L        |
| Take profit| Odd empate sobe (ex.: gol) → fecha com lucro |
| Stop loss  | Odd empate cai → fecha com perda controlada  |

O limite diário (parar o Lay Draw quando a banca cai X% no dia) foi **desativado** (`daily_loss_limit_pct = 0`). O bot segue rodando; só o limite **total** (20% da banca inicial) continua ativo, se quiser manter.
