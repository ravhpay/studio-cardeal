import os
import io
import traceback
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from supabase import create_client, Client

# Carrega as variáveis do arquivo .env com segurança
load_dotenv()

app = FastAPI(
    title="Studio Bia Cardeal Beauty API",
    description="API backend em Python com FastAPI integrada ao Supabase.",
    version="1.0.0"
)

# Configuração de CORS para permitir requisições do frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Credenciais puxadas diretamente do arquivo .env
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("⚠️ Erro: As variáveis SUPABASE_URL e SUPABASE_KEY não foram encontradas no arquivo .env!")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- MODELOS DE DADOS (Pydantic) ---

class ServicoCreate(BaseModel):
    nome: str
    preco: float
    duracao: int
    categoria: str
    desc: Optional[str] = None
    foto: Optional[str] = None

class AgendamentoCreate(BaseModel):
    cliente: str
    whatsapp: str
    obs: Optional[str] = None
    data: str
    horario: str
    servicos: List[str]
    total: float

class ConfigUpdate(BaseModel):
    nome: str
    sub: str
    endereco: str
    whatsapp: str
    bio: str
    foto_perfil: Optional[str] = None
    admin_senha: Optional[str] = None  # <--- Adicionado para suportar alteração de senha sem alterar o resto

class GaleriaCreate(BaseModel):
    url: str
    legenda: Optional[str] = None


# --- ROTAS DA API ---

@app.get("/")
def read_root():
    return {"message": "API do Studio Bia Cardeal Beauty a funcionar com sucesso!"}

# 1. Configurações do Studio
@app.get("/api/config")
def get_config():
    response = supabase.table("studio_config").select("*").single().execute()
    return response.data

@app.put("/api/config")
def update_config(config: ConfigUpdate):
    # Remove campos None/vazios da senha caso não tenham sido enviados para evitar sobrescrever com null se não desejado
    data_dict = config.dict(exclude_unset=True)
    response = supabase.table("studio_config").update(data_dict).eq("id", 1).execute()
    return {"message": "Configurações atualizadas", "data": response.data}

# 2. Serviços e Procedimentos
@app.get("/api/servicos")
def get_servicos():
    response = supabase.table("servicos").select("*").execute()
    return response.data

@app.post("/api/servicos")
def create_servico(servico: ServicoCreate):
    response = supabase.table("servicos").insert(servico.dict()).execute()
    return {"message": "Serviço criado", "data": response.data}

@app.delete("/api/servicos/{servico_id}")
def delete_servico(servico_id: int):
    supabase.table("servicos").delete().eq("id", servico_id).execute()
    return {"message": "Serviço eliminado"}

# 3. Galeria de Fotos
@app.get("/api/galeria")
def get_galeria():
    response = supabase.table("galeria").select("*").execute()
    return response.data

@app.post("/api/galeria")
def add_galeria(galeria: GaleriaCreate):
    response = supabase.table("galeria").insert(galeria.dict()).execute()
    return {"message": "Foto adicionada à galeria", "data": response.data}

@app.delete("/api/galeria/{foto_id}")
def delete_galeria(foto_id: int):
    supabase.table("galeria").delete().eq("id", foto_id).execute()
    return {"message": "Foto eliminada"}

# 4. Agendamentos
@app.get("/api/agendamentos")
def get_agendamentos():
    response = supabase.table("agendamentos").select("*").execute()
    return response.data

@app.post("/api/agendamentos")
def create_agendamento(agendamento: AgendamentoCreate):
    response = supabase.table("agendamentos").insert(agendamento.dict()).execute()
    return {"message": "Agendamento efetuado", "data": response.data}

@app.delete("/api/agendamentos/{agendamento_id}")
def delete_agendamento(agendamento_id: int):
    supabase.table("agendamentos").delete().eq("id", agendamento_id).execute()
    return {"message": "Agendamento eliminado"}

# 5. Upload Seguro para o Supabase Storage (Definitivo)
@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        safe_filename = file.filename.replace(" ", "_").replace("(", "").replace(")", "")
        file_path = f"{os.urandom(8).hex()}_{safe_filename}"
        
        # Envia os bytes diretamente (como a biblioteca storage3 exige)
        supabase.storage.from_("studio-bucket").upload(
            path=file_path,
            file=contents,
            file_options={"contentType": file.content_type, "upsert": "true"}
        )
        
        # Obtém a URL pública gerada
        public_url_res = supabase.storage.from_("studio-bucket").get_public_url(file_path)
        
        if isinstance(public_url_res, dict):
            url = public_url_res.get("publicUrl") or public_url_res.get("public_url")
        else:
            url = public_url_res
            
        return {"url": url}
    except Exception as e:
        print("❌ ERRO DETALHADO NO UPLOAD:")
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))