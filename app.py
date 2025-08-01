import streamlit as st
import pandas as pd
from zipfile import ZipFile
import io
import numpy as np

# ============================================================================
# FUNÇÃO PARA PROCESSAR O ZIP E GERAR O RELATÓRIO DE SITUAÇÃO
# ============================================================================
def processar_zip_situacao(arquivo_zip_bytes, outorga_diaria_definida):
    resumos = []
    
    try:
        with ZipFile(io.BytesIO(arquivo_zip_bytes), 'r') as zip_ref:
            arquivos_csv = sorted([f for f in zip_ref.namelist() if f.upper().endswith('.CSV')])
            
            if not arquivos_csv:
                st.error("Nenhum ficheiro .csv ou .CSV foi encontrado dentro do ficheiro ZIP.")
                return None

            for arquivo in arquivos_csv:
                with zip_ref.open(arquivo) as f:
                    df = pd.read_csv(f, encoding='ISO-8859-1', header=None)
                    
                    if df.empty:
                        continue
                        
                    df_filtrado = df.iloc[:, [0, 1, 2, 5]].copy()
                    df_filtrado.columns = ['id', 'data', 'hora', 'vazao_total']
                    
                    df_filtrado['vazao_total'] = pd.to_numeric(df_filtrado['vazao_total'], errors='coerce')
                    df_filtrado.dropna(subset=['vazao_total'], inplace=True)

                    if df_filtrado.empty:
                        continue
                    
                    # Coleta apenas os dados essenciais
                    resumos.append({
                        'data': df_filtrado['data'].iloc[0],
                        'hora_final': df_filtrado['hora'].iloc[-1],
                        'vazao_total_final': df_filtrado['vazao_total'].iloc[-1],
                        'vazao_outorgada': outorga_diaria_definida 
                    })

        if not resumos:
            st.error("Processamento concluído, mas nenhum ficheiro CSV com dados válidos foi encontrado.")
            return None

        # --- Preparação do DataFrame Final ---
        df_final = pd.DataFrame(resumos)
        df_final['data'] = pd.to_datetime(df_final['data'], errors='coerce', format='%Y/%m/%d')
        
        df_final.dropna(subset=['data'], inplace=True)
        if df_final.empty:
            st.error("Nenhuma data válida foi encontrada. Verifique se os ficheiros contêm datas no formato AAAA/MM/DD.")
            return None

        df_final = df_final.sort_values(by='data').reset_index(drop=True)
        
        # Cálculos principais
        df_final['vazao_diaria'] = df_final['vazao_total_final'].diff().fillna(0)
        
        # --- MUDANÇA: Adicionando a coluna "Situação" ---
        # Usamos np.where para aplicar a condição de forma eficiente
        df_final['situacao'] = np.where(df_final['vazao_diaria'] > df_final['vazao_outorgada'], 'Irregular', 'Regular')
        # O primeiro dia, com vazão 0, será sempre "Regular"
        df_final.loc[0, 'situacao'] = 'Regular'

        # Definindo a nova ordem das colunas
        ordem_colunas = ['data', 'hora_final', 'vazao_total_final', 'vazao_diaria', 'vazao_outorgada', 'situacao']
        df_final = df_final[ordem_colunas]
        num_dias = len(df_final)
        
        consumo_mensal_total = df_final['vazao_diaria'].sum()
        outorga_mensal_total = df_final['vazao_outorgada'].sum()
        
        df_final['data'] = df_final['data'].dt.strftime('%d/%m/%Y')
        
        # Criando a linha de totais (sem as colunas removidas)
        df_total_row = pd.DataFrame([{'data': 'TOTAL MENSAL', 
                                      'vazao_diaria': consumo_mensal_total,
                                      'vazao_outorgada': outorga_mensal_total}])
        df_final = pd.concat([df_final, df_total_row], ignore_index=True)

        # Atualizando os nomes das colunas para o relatório
        nomes_visuais = {'data': 'Data', 'hora_final': 'Hora Final Leitura', 'vazao_total_final': 'Vazão Acumulada Final', 
                         'vazao_diaria': 'Consumo Diário (m³)', 'vazao_outorgada': 'Outorga Diária (m³)',
                         'situacao': 'Situação'}
        df_final_formatado = df_final.rename(columns=nomes_visuais)

        # --- Criação do Arquivo Excel em Memória ---
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_final_formatado.to_excel(writer, sheet_name='Resumo Mensal', index=False)
            
            workbook = writer.book
            worksheet = writer.sheets['Resumo Mensal']

            header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'vcenter', 'align': 'center', 'fg_color': '#D7E4BC', 'border': 1})
            integer_format = workbook.add_format({'num_format': '#,##0', 'align': 'center', 'valign': 'vcenter'})
            text_format = workbook.add_format({'num_format': '@', 'align': 'center', 'valign': 'vcenter'})

            # Formatação de cores para a coluna "Situação"
            regular_format = workbook.add_format({'bg_color': '#C6EFCE', 'font_color': '#006100', 'align': 'center', 'valign': 'vcenter'})
            irregular_format = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006', 'align': 'center', 'valign': 'vcenter'})
            
            # Aplica a formatação condicional na coluna F (Situação)
            worksheet.conditional_format(f'F2:F{num_dias + 1}', {'type': 'cell', 'criteria': '==', 'value': '"Regular"', 'format': regular_format})
            worksheet.conditional_format(f'F2:F{num_dias + 1}', {'type': 'cell', 'criteria': '==', 'value': '"Irregular"', 'format': irregular_format})

            for col_num, value in enumerate(df_final_formatado.columns.values):
                worksheet.write(0, col_num, value, header_format)

            # Ajustando a formatação para o novo layout de colunas
            worksheet.set_column('A:A', 18) # Data
            worksheet.set_column('B:B', 18) # Hora Final Leitura
            worksheet.set_column('C:C', 22, integer_format) # Vazão Acumulada Final
            worksheet.set_column('D:D', 20, text_format) # Consumo Diário (m³)
            worksheet.set_column('E:E', 20, integer_format) # Outorga Diária (m³)
            worksheet.set_column('F:F', 15) # Situação

            # O gráfico permanece o mesmo, comparando Consumo (D) e Outorga (E)
            chart = workbook.add_chart({'type': 'column'})
            chart.add_series({'name': "='Resumo Mensal'!$D$1", 'categories': f"='Resumo Mensal'!$A$2:$A${num_dias + 1}", 'values': f"='Resumo Mensal'!$D$2:$D${num_dias + 1}"})
            chart.add_series({'name': "='Resumo Mensal'!$E$1", 'values': f"='Resumo Mensal'!$E$2:$E${num_dias + 1}"})
            chart.set_title({'name': 'Consumo Diário vs. Outorga Diária'})
            chart.set_x_axis({'name': 'Dia'}); chart.set_y_axis({'name': 'Volume (m³)'})
            worksheet.insert_chart('H2', chart, {'x_scale': 1.5, 'y_scale': 1.5})

        return output.getvalue()

    except Exception as e:
        st.error(f"Ocorreu um erro geral durante o processamento: {e}")
        import traceback
        st.error(traceback.format_exc())
        return None

# ============================================================================
# INTERFACE DO USUÁRIO COM STREAMLIT
# ============================================================================
st.set_page_config(page_title="Gerador de Resumo de Situação", layout="centered")

st.title("Gerador de Resumo de Situação de Consumo")
st.write("Por favor, envie o ficheiro .ZIP com os relatórios diários para gerar o resumo em Excel.")

outorga_input = st.number_input(
    label="Defina a Outorga Diária (m³):",
    min_value=0,
    value=9600,
    step=100
)

uploaded_file = st.file_uploader("Escolha o ficheiro ZIP", type="zip")

if uploaded_file is not None:
    bytes_data = uploaded_file.getvalue()
    
    with st.spinner("A processar os ficheiros... Por favor, aguarde."):
        resultado_excel = processar_zip_situacao(bytes_data, outorga_input)
    
    if resultado_excel:
        st.success("Resumo gerado com sucesso!")
        st.download_button(
            label="Baixar Resumo em Excel",
            data=resultado_excel,
            file_name="resumo_situacao_mensal.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )