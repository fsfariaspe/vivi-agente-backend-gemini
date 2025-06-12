import os
import psycopg2
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

def get_db_connection():
    """Cria e retorna uma nova conexão com o banco de dados."""
    try:
        conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            host=os.getenv("DB_HOST"),
            port="5432",
            sslmode="require"
        )
        return conn
    except Exception as e:
        logger.error(f"❌ Erro ao criar conexão com o banco de dados: {e}")
        return None

def salvar_conversa(numero_cliente, mensagem, nome_cliente):
    """Abre uma conexão, salva a conversa e fecha a conexão."""
    conn = get_db_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversas (numero_cliente, nome_cliente, mensagem_inicial)
                VALUES (%s, %s, %s)
                """,
                (numero_cliente, nome_cliente, mensagem)
            )
            conn.commit()
            logger.info("💾 Conversa salva para o cliente: %s", nome_cliente)
    except Exception as e:
        logger.error(f"❌ Erro ao salvar conversa no banco: {e}")
        conn.rollback()
    finally:
        if conn:
            conn.close()

def buscar_nome_cliente(numero_cliente):
    """Abre uma conexão, busca o nome mais recente e fecha a conexão."""
    conn = get_db_connection()
    if not conn:
        return None
    nome = None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT nome_cliente FROM conversas WHERE numero_cliente = %s AND nome_cliente IS NOT NULL ORDER BY data_inicio DESC LIMIT 1",
                (numero_cliente,)
            )
            resultado = cur.fetchone()
            if resultado:
                nome = resultado[0]
    except Exception as e:
        logger.error(f"❌ Erro ao buscar nome do cliente: {e}")
    finally:
        if conn:
            conn.close()
    return nome