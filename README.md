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

Abra `http://127.0.0.1:8000`.

Uso direto pela linha de comando:

```bash
python converter.py documento.pdf -o output/documento
```

O resultado fica autocontido na pasta escolhida. O PDF original nao e incorporado ao HTML.

## Limites conhecidos

PDF e uma linguagem de desenho, nao de layout. Textos e formas sao reconstruidos por
coordenadas absolutas. Fontes nao instaladas no navegador recebem uma alternativa
compativel. Curvas complexas sao preservadas como SVG; isso continua sendo HTML vetorial,
nao uma captura da pagina. PDFs digitalizados precisam de OCR, que nao faz parte desta
primeira versao.

