# PDF Neural - PDF para formulario HTML

Converte PDFs de formularios em HTML editavel, sem usar uma imagem da pagina como fundo.
O conversor recria texto, linhas, retangulos, imagens e campos como elementos HTML/SVG.

## O que ele faz

- le campos AcroForm nativos;
- infere campos visuais a partir de linhas, caixas e rotulos;
- infere tipos (`text`, `date`, `email`, `tel`, `number`, `checkbox` e `textarea`);
- extrai imagens e logotipos para a pasta `assets/`;
- gera `index.html` e `fields.json`;
- inclui uma interface local para enviar o PDF e baixar o resultado em ZIP.

## Instalacao e uso

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Abra `http://127.0.0.1:8000`. Na interface, envie um arquivo local ou informe uma
URL publica HTTP/HTTPS que aponte para o PDF. Downloads remotos possuem limite de
30 MB e enderecos locais ou de rede privada sao bloqueados.

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
corpo contem `status: "completed"` e `result` com `fields`, `preview_url` e
`download_url`. Em caso de erro, contem `status: "failed"` e `error`. O envio do
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
