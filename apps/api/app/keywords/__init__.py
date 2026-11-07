"""Palavras-chave monitoradas pelo administrador: todo prompt que contém a palavra gera um alerta, com pontuação opcional.

Pasta própria para não misturar com o motor de detecção: o motor nunca conhece estas regras. Elas são aplicadas na ingestão
(`app.services.ingest`), sobre o texto recebido, ainda em memória. A palavra procurada fica guardada; o trecho do prompt, não.
"""
