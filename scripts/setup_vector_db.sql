-- Função de busca híbrida (Texto + Vetor) com RRF (Reciprocal Rank Fusion)
-- V2: Adiciona suporte a boost por categoria
CREATE OR REPLACE FUNCTION hybrid_search_v2(
    query_text TEXT,
    query_embedding VECTOR(1536),
    match_count INT,
    full_text_weight FLOAT = 1.0,
    semantic_weight FLOAT = 1.0,
    setor_boost FLOAT = 0.5,
    rrf_k INT = 50
)
RETURNS TABLE (
    text TEXT,
    metadata JSONB,
    score FLOAT,
    rank INT
) AS $$
BEGIN
    RETURN QUERY
    WITH full_text AS (
        SELECT 
            id, 
            ROW_NUMBER() OVER (ORDER BY ts_rank_cd(to_tsvector('portuguese', p.text), plainto_tsquery('portuguese', query_text)) DESC) as rank_ix
        FROM produtos_vectors_ean p
        WHERE to_tsvector('portuguese', p.text) @@ plainto_tsquery('portuguese', query_text)
        LIMIT match_count
    ),
    semantic AS (
        SELECT 
            id, 
            ROW_NUMBER() OVER (ORDER BY embedding <=> query_embedding) as rank_ix
        FROM produtos_vectors_ean
        ORDER BY embedding <=> query_embedding
        LIMIT match_count
    )
    SELECT
        p.text,
        p.metadata,
        COALESCE(
            (1.0 / (rrf_k + ft.rank_ix) * full_text_weight) + 
            (1.0 / (rrf_k + s.rank_ix) * semantic_weight),
            0.0
        ) * (
            CASE 
                -- Aplica boost se o produto for do setor HORTI-FRUTI ou FRIGORIFICO (carnes)
                -- O metadata é um JSONB, então extraímos o campo 'setor'
                WHEN p.metadata->>'setor' IN ('HORTI-FRUTI', 'FRIGORIFICO') THEN (1.0 + setor_boost)
                ELSE 1.0
            END
        ) as score,
        ROW_NUMBER() OVER (ORDER BY 
            COALESCE(
                (1.0 / (rrf_k + ft.rank_ix) * full_text_weight) + 
                (1.0 / (rrf_k + s.rank_ix) * semantic_weight),
                0.0
            ) * (
                CASE 
                    WHEN p.metadata->>'setor' IN ('HORTI-FRUTI', 'FRIGORIFICO') THEN (1.0 + setor_boost)
                    ELSE 1.0
                END
            ) DESC
        )::INT as rank
    FROM produtos_vectors_ean p
    LEFT JOIN full_text ft ON p.id = ft.id
    LEFT JOIN semantic s ON p.id = s.id
    WHERE ft.id IS NOT NULL OR s.id IS NOT NULL
    ORDER BY score DESC
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;
