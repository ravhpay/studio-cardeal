import os
import traceback
from datetime import datetime, timedelta, timezone
from typing import Optional, List
import jwt
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from supabase import create_client, Client
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

load_dotenv()

# Inicialização do Rate Limiter por IP
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Studio Bia Cardeal Beauty API",
    description="API backend segura em Python com FastAPI integrada ao Supabase.",
    version="2.2.1"
)

# Vincula o Limiter ao app FastAPI
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS 
ORIGENS_PERMITIDAS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "https://sensualepaixao.com.br",
    "https://www.sensualepaixao.com.br",
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGENS_PERMITIDAS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Desativa cache para rotas da API em tempo real
@app.middleware("http")
async def disable_cache(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
JWT_SECRET = os.getenv("JWT_SECRET", "chave-padrao-troque-no-env")
ALGORITHM = "HS256"

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Erro: SUPABASE_URL e SUPABASE_KEY nao encontrados no .env!")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

def gerar_hash_senha(senha: str) -> str:
    return pwd_context.hash(senha)

def verificar_senha(senha_plana: str, senha_hash: str) -> bool:
    if senha_plana == senha_hash:
        return True
    if not senha_hash.startswith("$2b$"):
        return senha_plana == senha_hash
    return pwd_context.verify(senha_plana, senha_hash)

def criar_token_jwt() -> str:
    expiracao = datetime.now(timezone.utc) + timedelta(hours=12)
    payload = {"sub": "admin", "exp": expiracao}
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)

def verificar_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        if payload.get("sub") != "admin":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido.")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessao expirada.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Acesso nao autorizado.")

# --- Modelos Pydantic ---
class LoginRequest(BaseModel):
    senha: str

class ServicoCreate(BaseModel):
    nome: str
    preco: float = Field(..., gt=0)
    duracao: int = Field(..., gt=0)
    categoria: str
    desc: Optional[str] = None
    foto: Optional[str] = None

class ServicoUpdate(BaseModel):
    nome: Optional[str] = None
    preco: Optional[float] = Field(None, gt=0)
    duracao: Optional[int] = Field(None, gt=0)
    categoria: Optional[str] = None
    desc: Optional[str] = None
    foto: Optional[str] = None

class AgendamentoCreate(BaseModel):
    cliente: str
    whatsapp: str
    obs: Optional[str] = None
    data: str  # Formato: YYYY-MM-DD
    horario: str  # Formato: HH:MM
    servicos: List[str]
    total: float = Field(..., gt=0)

class ConfigUpdate(BaseModel):
    nome: Optional[str] = None
    sub: Optional[str] = None
    endereco: Optional[str] = None
    whatsapp: Optional[str] = None
    bio: Optional[str] = None
    foto_perfil: Optional[str] = None
    admin_senha: Optional[str] = None

class GaleriaCreate(BaseModel):
    url: str
    legenda: Optional[str] = None

class BloqueioCreate(BaseModel):
    data_inicio: str  # Formato: YYYY-MM-DD
    data_fim: Optional[str] = None  # Formato: YYYY-MM-DD (para intervalo de dias/semana/mês)
    horario_inicio: Optional[str] = None  # "TODOS" ou ex: "12:00"
    horario_fim: Optional[str]     = None
    motivo: Optional[str] = None

# --- Endpoints ---
@app.get("/")
def read_root():
    return {"message": "API do Studio Bia Cardeal Beauty v2.2.1 online!", "status": "active"}

@app.post("/api/login")
@limiter.limit("5/minute")
def login_admin(request: Request, dados: LoginRequest):
    try:
        res = supabase.table("studio_config").select("admin_senha").eq("id", 1).single().execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Configuracao nao encontrada.")
        
        senha_banco = res.data.get("admin_senha")
        if not senha_banco or not verificar_senha(dados.senha, senha_banco):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Senha incorreta.")
        
        token = criar_token_jwt()
        return {"access_token": token, "token_type": "bearer"}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Erro interno no login: {str(e)}")

@app.get("/api/config")
def get_config():
    try:
        response = (
            supabase.table("studio_config")
            .select("id, nome, sub, endereco, whatsapp, bio, foto_perfil")
            .eq("id", 1)
            .single()
            .execute()
        )
        return response.data
    except Exception as e:
        raise HTTPException(status_code=404, detail="Configuracoes do studio nao encontradas.")

@app.put("/api/config", dependencies=[Depends(verificar_admin)])
def update_config(config: ConfigUpdate):
    try:
        data_dict = config.model_dump(exclude_unset=True)
        if data_dict.get("admin_senha"):
            data_dict["admin_senha"] = gerar_hash_senha(data_dict["admin_senha"])
        else:
            data_dict.pop("admin_senha", None)
            
        response = supabase.table("studio_config").update(data_dict).eq("id", 1).execute()
        return {"message": "Configuracoes atualizadas com sucesso", "data": response.data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/servicos")
def get_servicos():
    try:
        response = supabase.table("servicos").select("*").order("id").execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/servicos", dependencies=[Depends(verificar_admin)])
def create_servico(servico: ServicoCreate):
    try:
        response = supabase.table("servicos").insert(servico.model_dump()).execute()
        return {"message": "Servico criado com sucesso", "data": response.data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/api/servicos/{servico_id}", dependencies=[Depends(verificar_admin)])
def update_servico(servico_id: int, servico: ServicoUpdate):
    try:
        data_dict = servico.model_dump(exclude_unset=True)
        response = supabase.table("servicos").update(data_dict).eq("id", servico_id).execute()
        return {"message": "Servico atualizado com sucesso", "data": response.data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/servicos/{servico_id}", dependencies=[Depends(verificar_admin)])
def delete_servico(servico_id: int):
    try:
        supabase.table("servicos").delete().eq("id", servico_id).execute()
        return {"message": "Servico eliminado"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/galeria")
def get_galeria():
    try:
        response = supabase.table("galeria").select("*").order("id", desc=True).execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/galeria", dependencies=[Depends(verificar_admin)])
def add_galeria(galeria: GaleriaCreate):
    try:
        response = supabase.table("galeria").insert(galeria.model_dump()).execute()
        return {"message": "Foto adicionada a galeria", "data": response.data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/galeria/{foto_id}", dependencies=[Depends(verificar_admin)])
def delete_galeria(foto_id: int):
    try:
        supabase.table("galeria").delete().eq("id", foto_id).execute()
        return {"message": "Foto eliminada"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/agendamentos", dependencies=[Depends(verificar_admin)])
def get_agendamentos():
    try:
        response = supabase.table("agendamentos").select("*").order("data").order("horario").execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/horarios-ocupados/{data}")
def get_horarios_ocupados(data: str):
    try:
        res_ag = supabase.table("agendamentos").select("horario").eq("data", data).execute()
        horarios = [item["horario"] for item in res_ag.data]

        res_blq = supabase.table("bloqueios").select("*").eq("data", data).execute()
        for blq in res_blq.data:
            if not blq.get("horario_inicio") or blq.get("horario_inicio") == "TODOS":
                horarios.extend(['09:00', '10:00', '11:00', '13:00', '14:00', '15:00', '16:00', '17:00', '18:00'])
            else:
                horarios.append(blq["horario_inicio"])
                
        return list(set(horarios))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/agendamentos")
def create_agendamento(agendamento: AgendamentoCreate):
    try:
        conflito = (
            supabase.table("agendamentos")
            .select("id")
            .eq("data", agendamento.data)
            .eq("horario", agendamento.horario)
            .execute()
        )
        if conflito.data:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Este horario ja foi reservado por outra cliente."
            )
        response = supabase.table("agendamentos").insert(agendamento.model_dump()).execute()
        return {"message": "Agendamento efetuado com sucesso!", "data": response.data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/agendamentos/{agendamento_id}", dependencies=[Depends(verificar_admin)])
def delete_agendamento(agendamento_id: int):
    try:
        supabase.table("agendamentos").delete().eq("id", agendamento_id).execute()
        return {"message": "Agendamento eliminado"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# --- Rotas de Bloqueios & Folgas (Com Intervalo de Datas e Todos os Horários) ---
@app.get("/api/bloqueios")
def get_bloqueios():
    try:
        response = supabase.table("bloqueios").select("*").order("data").execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/bloqueios", dependencies=[Depends(verificar_admin)])
def create_bloqueio(bloqueio: BloqueioCreate):
    try:
        d_inicio = datetime.strptime(bloqueio.data_inicio, "%Y-%m-%d")
        d_fim = datetime.strptime(bloqueio.data_fim, "%Y-%m-%d") if bloqueio.data_fim else d_inicio
        
        if d_fim < d_inicio:
            raise HTTPException(status_code=400, detail="A data final nao pode ser anterior a data inicial.")
            
        current_date = d_inicio
        registros_inseridos = []
        
        while current_date <= d_fim:
            data_str = current_date.strftime("%Y-%m-%d")
            
            payload = {
                "data": data_str,
                "horario_inicio": None if bloqueio.horario_inicio == "TODOS" else bloqueio.horario_inicio,
                "horario_fim": bloqueio.horario_fim,
                "motivo": bloqueio.motivo or "Folga / Ferias"
            }
            
            response = supabase.table("bloqueios").insert(payload).execute()
            if response.data:
                registros_inseridos.extend(response.data)
            current_date += timedelta(days=1)
            
        return {"message": "Bloqueios criados com sucesso", "data": registros_inseridos}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/bloqueios/{bloqueio_id}", dependencies=[Depends(verificar_admin)])
def delete_bloqueio(bloqueio_id: int):
    try:
        supabase.table("bloqueios").delete().eq("id", bloqueio_id).execute()
        return {"message": "Bloqueio removido com sucesso"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/upload", dependencies=[Depends(verificar_admin)])
async def upload_image(file: UploadFile = File(...)):
    tipos_permitidos = ["image/jpeg", "image/png", "image/webp", "image/jpg"]
    if file.content_type not in tipos_permitidos:
        raise HTTPException(status_code=400, detail="Formato invalido. Envie apenas JPG, PNG ou WebP.")
    try:
        contents = await file.read()
        if len(contents) > 5 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="A imagem excede o limite maximo de 5 MB.")
        
        safe_filename = file.filename.replace(" ", "_").replace("(", "").replace(")", "")
        file_path = f"{os.urandom(8).hex()}_{safe_filename}"
        
        supabase.storage.from_("studio-bucket").upload(
            path=file_path,
            file=contents,
            file_options={"content-type": file.content_type, "upsert": "true"}
        )
        
        public_url_res = supabase.storage.from_("studio-bucket").get_public_url(file_path)
        if isinstance(public_url_res, dict):
            url = public_url_res.get("publicUrl") or public_url_res.get("public_url")
        else:
            url = public_url_res
            
        return {"url": url}
    except HTTPException:
        raise
    except Exception as e:
        print("ERRO DETALHADO NO UPLOAD:")
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))
