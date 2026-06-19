# PDF Neural - PDF para HTML e mapeamento JSON

Converte PDFs em uma representacao HTML fiel, sem usar uma imagem da pagina como fundo.
O conversor recria texto, linhas, retangulos e imagens como elementos HTML/SVG. Os
campos detectados nao viram formularios HTML: seu mapeamento e gravado separadamente
em `fields.json` para permitir o preenchimento posterior do PDF.

## O que ele faz

- le campos AcroForm nativos;
- infere campos visuais a partir de linhas, caixas e rotulos;
- infere tipos (`text`, `date`, `email`, `tel`, `number`, `checkbox` e `textarea`);
- extrai imagens e logotipos para a pasta `assets/`;
- detecta grades de tabelas, celulas mescladas e celulas vazias destinadas a valores;
- gera `index.html` sem campos de formulario e `fields.json` com nome, tipo, pagina,
  coordenadas e dimensoes de cada campo, alem de `tables.json` com a estrutura de
  linhas, colunas, celulas e seus textos;
- inclui uma interface local para enviar o PDF e baixar o resultado em ZIP.

## Instalacao e uso

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

## Detector neural de tabelas

O detector neural e opcional e complementa a deteccao geometrica existente. Ele
usa uma U-Net compacta para segmentar as regioes de tabela e aprende com mascaras
especificas das linhas da grade. Apos localizar a regiao, a cabeca estrutural
recupera linhas e colunas; em PDFs vetoriais preserva a cor e espessura originais,
e em documentos digitalizados estima ambas diretamente dos pixels.

```bash
pip install -r requirements-ml.txt

# Aceita arquivos e/ou pastas; procura PDFs recursivamente nas pastas.
python neural_table_detector.py prepare tmp/pdfs -o data/tables
python neural_table_detector.py train data/tables -o models/table_detector.pt --epochs 30
python neural_table_detector.py detect documento.pdf \
  --model models/table_detector.pt -o output/neural-tables.json
```

Para corrigir falsos positivos junto as bordas sem descartar o aprendizado anterior,
use ajuste fino. O treino pondera como negativos os pixels imediatamente externos a
cada tabela, evitando incluir campos proximos como `Data` e `Assinatura`:

```bash
python neural_table_detector.py train data/uepg/tables \
  --resume models/uepg_table_detector.pt \
  -o models/uepg_table_detector.pt --epochs 10 --learning-rate 0.0002
```

Um modelo treinado com os documentos publicos do Mestrado em Direito da UEPG
esta disponivel em `models/uepg_table_detector.pt`. O corpus correspondente fica
em `data/uepg/` (20 PDFs, 65 paginas, 25 paginas positivas e 40 negativas):

```bash
python neural_table_detector.py detect documento.pdf \
  --model models/uepg_table_detector.pt -o output/neural-tables.json
```

Cada resultado contem pagina, coordenadas PDF, dimensoes, confianca,
`row_count`, `column_count`, `lines` (coordenadas, espessura e cor) e
`source: "neural"`. Um unico PDF permite validar o fluxo, mas um modelo robusto
normalmente exige dezenas ou centenas de paginas variadas, incluindo paginas sem
tabelas. Revise as mascaras em `data/tables/masks/` e
`data/tables/grid-masks/` antes do treino; elas sao os rotulos aprendidos pela rede.

Abra `http://127.0.0.1:8000`. Na interface, envie um arquivo local ou informe uma
URL publica HTTP/HTTPS que aponte para o PDF. Downloads remotos possuem limite de
30 MB e enderecos locais ou de rede privada sao bloqueados.

A interface executa automaticamente o modelo `models/uepg_table_detector.pt` e
mostra as grades encontradas em **Tabelas - rede neural**. O arquivo
`neural-tables.json` tambem e incluido no ZIP. Na previa HTML, linhas e colunas sao
renderizadas nas coordenadas detectadas usando a cor dos tracos do documento de
origem. Para trocar o checkpoint ou ajustar a sensibilidade:

```bash
TABLE_MODEL=models/uepg_table_detector.pt \
NEURAL_THRESHOLD=0.7 \
NEURAL_MIN_CONFIDENCE=0.65 \
python app.py
```

Por padrao, uma falha neural e registrada e a conversao geometrica continua. Use
`NEURAL_REQUIRED=true` quando a requisicao inteira deva falhar caso o modelo nao
possa ser executado.

A documentacao interativa Swagger fica em `http://127.0.0.1:8000/docs` e a
especificacao OpenAPI 3.1 em `http://127.0.0.1:8000/openapi.json`.

Uso direto pela linha de comando:

```bash
python converter.py documento.pdf -o output/documento
```

O resultado fica autocontido na pasta escolhida. O PDF original nao e incorporado ao HTML.

## API assincrona com callback

Envie as URLs do PDF e do callback em JSON. Ambas precisam ser publicas; enderecos
locais e privados sao recusados. O campo `reference` e opcional e e devolvido sem
alteracoes para permitir a correlacao com o sistema de origem.

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "pdf_url": "https://exemplo.com/formulario.pdf",
    "callback_url": "https://sistema.exemplo.com/callbacks/pdf",
    "reference": "documento-123"
  }'
```

A API responde imediatamente com HTTP `202`:

```json
{
  "job_id": "9a46c0ef8db14a119a006f239683ef9f",
  "reference": "documento-123",
  "status": "queued",
  "status_url": "https://pdf.exemplo.com/api/jobs/9a46c0ef8db14a119a006f239683ef9f"
}
```

Ao terminar, o callback recebe um `POST application/json`. Em caso de sucesso, o
corpo contem `status: "completed"` e `result` com `fields`, `tables`, `preview_url`
e `download_url`. Em caso de erro, contem `status: "failed"` e `error`. O envio do
callback e tentado ate tres vezes. O estado tambem pode ser consultado com
`GET /api/jobs/{job_id}`.

Em producao, configure a URL externa usada nos links e a quantidade de conversoes
simultaneas:

```bash
PUBLIC_BASE_URL=https://pdf.exemplo.com PDF_WORKERS=4 python app.py
```

## Deploy com Coolify

Crie um recurso do tipo **Docker Compose** apontando para este repositorio. O servico
publica a porta `8000`, possui healthcheck e salva os jobs no volume persistente
`pdf-neural-data`.

Configure no Coolify:

```env
PUBLIC_BASE_URL=https://pdf.exemplo.com
PDF_WORKERS=2
```

Associe o dominio do recurso a porta interna `8000`. A porta nao e publicada no host;
o proxy do Coolify acessa o servico diretamente pela rede Docker, evitando conflitos
com outras aplicacoes. `PUBLIC_BASE_URL` deve ser a URL publica sem barra no final,
para que callbacks e links de resultados usem o dominio correto.

Para executar localmente com a mesma configuracao:

```bash
docker compose up --build
```

## Limites conhecidos

PDF e uma linguagem de desenho, nao de layout. Textos e formas sao reconstruidos por
coordenadas absolutas. Fontes nao instaladas no navegador recebem uma alternativa
compativel. Curvas complexas sao preservadas como SVG; isso continua sendo HTML vetorial,
nao uma captura da pagina. PDFs digitalizados precisam de OCR, que nao faz parte desta
primeira versao.
