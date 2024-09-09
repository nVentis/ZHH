from ast import literal_eval as make_tuple
from glob import glob
from dateutil import parser
from typing import Optional, Union, Iterable
from tqdm.auto import tqdm
import os.path as osp
import json
import numpy as np
import uproot as ur
import awkward as ak

DEFAULTS = {
    'PROD_NAME': '500-TDR_ws',
    'ILD_VERSION': 'ILD_l5_o1_v02'
}

def get_preselection_meta(DATA_ROOT:str)->dict:
    metafile = glob(f'{DATA_ROOT}/htcondor_jobs*.json')[0]
    with open(metafile) as file:
        meta = json.load(file)
        
    return meta

def file_get_polarization(src_path:str)->tuple[int, int]:
    pol_e = -1 if '.eL.p' in src_path else (+1 if '.eR.p' in src_path else 0)
    pol_p = -1 if '.pL.' in src_path else (+1 if '.pR.' in src_path else 0)
    
    if pol_e == 0 or pol_p == 0:
        print(f'Warning: Encountered 0 polarization (?)')
        
    return pol_e, pol_p

def parse_sample_path(src_path:str,
                    PROD_NAME:str=DEFAULTS['PROD_NAME'],
                    ILD_VERSION:str=DEFAULTS['ILD_VERSION'])->tuple:
    loc = src_path.split(f'/{PROD_NAME}/')[1]
    loc = loc.split(f'/{ILD_VERSION}/')[0]
    polarization = file_get_polarization(src_path)
    
    return (loc, polarization)

def parse_json(json_path:str):
    with open(json_path, 'r') as file:
        content = json.load(file)
        
    return content

def get_preselection_summary_for_branch(
            DATA_ROOT:str,
            branch:Union[int,str],
            PROD_NAME:str=DEFAULTS['PROD_NAME'],
            ILD_VERSION:str=DEFAULTS['ILD_VERSION']):
    
    branch = int(branch)
    
    try:
        with open(f'{DATA_ROOT}/{branch}_Source.txt') as file:
            src_path = file.read().strip()            
    except:
        src_path = ''
    
    try: 
        with open(f'{DATA_ROOT}/{branch}_FinalStateMeta.json') as jsonfile:
            fs_meta = json.load(jsonfile)
            process = fs_meta['processName']  
    except:
        process = ''
    
    try:
        with open(f'{DATA_ROOT}/stdall_{branch}To{branch+1}.txt') as file:
            signals = ['start time    :', 'end time      :', 'job exit code :']
            values = [0, 0, 0]
            lsig = len(signals)
            
            for line in file.readlines():
                for i in range(lsig):
                    if line.startswith(signals[i]):
                        values[i] = line.split(f'{signals[i]} ')[1].strip()
                    elif src_path == '' and '--global.LCIOInputFiles=' in line:
                        src_path = line.split('--global.LCIOInputFiles=')[1].strip().split(' --constant.OutputDirectory=')[0]

            for i in [0, 1]:
                if values[i] != '':
                    if ' (' in values[i]:
                        values[i] = values[i].split(' (')[0]
                    
                    values[i] = float(parser.parse(values[i]).timestamp())
    except:
        values = [0, 0, 0]
    
    loc = ''
    polarization = (0, 0)
    if src_path != '':
        loc, polarization = parse_sample_path(src_path, PROD_NAME=PROD_NAME, ILD_VERSION=ILD_VERSION)
            
    return (branch, loc, process, polarization[0], polarization[1], src_path, values[0], values[1], values[1] - values[0], int(values[2]))

def get_preselection_summary(DATA_ROOT:str, meta:dict)->np.ndarray:
    """_summary_

    Args:
        meta (dict): result returned from get_preselection_meta()

    Returns:
        np.ndarray: _description_
    """
    
    jobs = meta['jobs']
    dtype = [
        ('status', '<U16'),
        ('branch', 'I'),
        ('loc', '<U32'),
        ('process', '<U32'),
        ('pol_e', 'B'),
        ('pol_p', 'B'),
        ('src', '<U255'),
        ('tStart', 'f'),
        ('tEnd', 'f'),
        ('tDuration', 'f'),
        ('exitCode', 'i')]
    
    results = np.empty(0, dtype=dtype)

    for job_key in jobs:
        branch = jobs[job_key]['branches'][0]
        status = jobs[job_key]['status']
        
        ev = get_preselection_summary_for_branch(DATA_ROOT, branch)
        entry = (status, *ev)

        results = np.append(results, np.array([entry], dtype=dtype))
    
    return results

# https://doi.org/10.1016/j.physrep.2007.12.003
def w_prefacs(Pem, Pep):
    return (
        (1-Pem)*(1-Pep)/4, # LL
        (1-Pem)*(1+Pep)/4, # LR
        (1+Pem)*(1-Pep)/4, # RL
        (1+Pem)*(1+Pep)/4 # RR
    )
    

w_em_ep = {
    'LL': 0.315,
    'LR': 0.585,
    'RL': 0.035,
    'RR': 0.065
}

def get_pol_key(pol_em:int, pol_ep:int)->str:
    key_em = ('L' if pol_em == -1 else ('R' if pol_em == 1 else 'N'))
    key_ep = ('L' if pol_ep == -1 else ('R' if pol_ep == 1 else 'N'))
    return key_em + key_ep

def get_w_pol(pol_em:int, pol_ep:int)->float:
    key = get_pol_key(pol_em, pol_ep)
    
    if not (key in w_em_ep):
        raise Exception(f'Unhandled polarization {key}')
    
    return w_em_ep[key]

def sample_weight(process_sigma_fb:float,
                  pol:tuple[int, int],
                  n_gen:int=1,
                  lum_inv_ab:Optional[float]=2.)->float:
    
    w_pol = get_w_pol(*pol)    
    return process_sigma_fb * 1000 *lum_inv_ab * w_pol / n_gen

def get_preselection_passes(
    DATA_ROOT:str,
    version:str='v1')->np.ndarray:
    
    dtype = [
        ('process', '<U60'),
        ('pol_e', 'i'),
        ('pol_p', 'i'),
        ('n_gen', 'i'),
        ('cross_sec', 'f'),
        ('cross_sec_err', 'f'),
        ('n_pass_llhh', 'i'),
        ('n_pass_vvhh', 'i'),
        ('n_pass_qqhh', 'i'),
        ('weight', 'f'),
        ('proc_pol', '<U64')]

    results = np.empty(0, dtype=dtype)
    finished = glob(f'{DATA_ROOT}/*_Source.txt')
    finished.sort()

    for f in (pbar := tqdm(finished)):
        branch = f.split(f'{version}/')[1].split('_Source.txt')[0]
        
        if osp.isfile(f'{DATA_ROOT}/{branch}_FinalStateMeta.json'):
            # Source file is written at the very end -> .root files exist
            
            with open(f, 'r') as file:
                src_spec = file.read()
                if src_spec.startswith('('):
                    src_file, chunk_start, chunk_end = make_tuple(src_spec)
                else:
                    src_file = src_spec
                
            # Read metadata
            with open(f'{DATA_ROOT}/{branch}_FinalStateMeta.json', 'r') as file:
                meta = json.load(file)
                
                # {'crossSection': 133070.796875, 'crossSectionError': 78.4000015258789, 'eventWeight': 1.0, 'nEvtSum': 995, 'polElectron': -1.0, 'polPositron': 1.0, 'processId': 250127, 'processName': '2f_z_bhabhang', 'run': 250127}
                
            n_gen = meta['nEvtSum']
            proc = meta["processName"]
            
            loc, pol = parse_sample_path(src_file)
            procpol = f'{proc}_{get_pol_key(*pol)}'
            
            pbar.set_description(f'Adding {n_gen} events from branch {branch} ({procpol})')
            
            if not procpol in results['proc_pol']:
                results = np.append(results, [np.array([
                    (proc, pol[0], pol[1], n_gen, meta['crossSection'], meta['crossSectionError'], 0, 0, 0, 0., procpol)
                ], dtype=dtype)])
            else:
                results['n_gen'][results['proc_pol'] == procpol] += n_gen
                
            for presel in ['llHH', 'vvHH', 'qqHH']:
                with ur.open(f'{DATA_ROOT}/{branch}_PreSelection_{presel}.root') as rf:
                    passed = rf['eventTree']['preselPassed'].array()
                    
                    n_items = len(passed)
                    if n_items != n_gen:
                        raise Exception('Constraint mismatch')
                    
                    n_passed = np.sum(passed)
                    results[f'n_pass_{presel.lower()}'][results['proc_pol'] == procpol] += n_passed
                    
    for entry in results:
        pol = (entry['pol_e'], entry['pol_p'])
        results['weight'][results['proc_pol'] == entry['proc_pol']] = sample_weight(entry['cross_sec'], pol, entry['n_gen'])

    results = results[np.argsort(results['proc_pol'])]
    
    return results

def extract_dijet_masses(dijetMass:ur.TBranch)->tuple[np.ndarray, np.ndarray]:
    aka = dijetMass.array()
    mask = ak.num(aka) > 0

    mh1 = np.array(ak.fill_none(aka.mask[mask][:, 0], -1), dtype='f')
    mh2 = np.array(ak.fill_none(aka.mask[mask][:, 1], -1), dtype='f')
    
    return mh1, mh2

def presel_stack(DATA_ROOT:str,
                 processes:np.ndarray,
                 chunks_f:np.ndarray,
                 branches:list,
                 kinematics:bool=False)->np.ndarray:   
            
    dtype = [
        ('branch', chunks_f.dtype['branch']), # np.uint32
        ('pid', 'H'), # np.uint16
        ('event', 'I'), # max. encountered: 15 797 803 << 4 294 967 295 (max of uint32)
        ('event_category', 'B'), # np.uint8
        
        ('ll_pass', 'B'),
        ('vv_pass', 'B'),
        ('qq_pass', 'B'),
    ]
    
    if kinematics:
        for dt in [
            ('xx_thrust', 'f'),
            ('xx_e_vis', 'f'),
            ('xx_pt_miss', 'f'),
            ('xx_nisoleps', 'B'),
        
            # llHH
            ('ll_mh1', 'f'),
            ('ll_mh2', 'f'),
            ('ll_nbjets', 'B'),
            
            ('ll_dilepton_type', 'B'),
            ('ll_mz', 'f'),
            
            # vvHH
            ('vv_mh1', 'f'),
            ('vv_mh2', 'f'),
            ('vv_nbjets', 'B'),
            
            ('vv_mhh', 'f'),
            
            # qqHH
            ('qq_mh1', 'f'),
            ('qq_mh2', 'f'),
            ('qq_nbjets', 'B')
        ]:
            dtype.append(dt)
    
    r_size = chunks_f[np.isin(chunks_f['branch'], branches)]['chunk_size_factual'].sum()
    results = np.zeros(r_size, dtype=dtype)
    
    pointer = 0
    
    for branch in tqdm(branches):
        chunk_size = chunks_f[chunks_f['branch'] == branch]['chunk_size_factual'][0]
        chunk = np.zeros(chunk_size, dtype=dtype)
        
        # ('vv_jet1_b_tag', 'f'),
        #    ('vv_jet2_b_tag', 'f'),
        #    ('vv_jet3_b_tag', 'f'),
        #    ('vv_jet4_b_tag', 'f'),
        
        proc_pol = chunks_f[chunks_f['branch'] == branch]['proc_pol'][0]
        chunk['pid'] = processes[processes['proc_pol'] == proc_pol]['pid'][0]
        chunk['branch'] = branch
        
        with ur.open(f'{DATA_ROOT}/{branch}_FinalStates.root:eventTree') as rf:
            chunk['event'] = rf['event'].array()
            chunk['event_category'] = rf['event_category'].array()
        
        with ur.open(f'{DATA_ROOT}/{branch}_PreSelection_qqHH.root:eventTree') as rf:            
            chunk['qq_pass'] = rf['preselPassed'].array()
            
            if kinematics:
                chunk['xx_thrust'] = rf['thrust'].array()
                chunk['xx_e_vis'] = rf['Evis'].array()
                chunk['xx_pt_miss'] = rf['missingPT'].array()
                chunk['xx_nisoleps'] = rf['nIsoLeptons'].array()
                chunk['qq_nbjets'] = rf['nbjets'].array()
            
                mh1, mh2 = extract_dijet_masses(rf['dijetMass'])
                chunk['qq_mh1'] = mh1
                chunk['qq_mh2'] = mh2
        
        for presel in ['ll', 'vv']:
            with ur.open(f'{DATA_ROOT}/{branch}_PreSelection_{presel}HH.root:eventTree') as rf:
                chunk[f'{presel}_pass'] = rf['preselPassed'].array()
                
                if kinematics:
                    chunk[f'{presel}_nbjets'] = rf['nbjets'].array()
                    
                    mh1, mh2 = extract_dijet_masses(rf['dijetMass'])
                    chunk[f'{presel}_mh1'] = mh1
                    chunk[f'{presel}_mh2'] = mh2
                
                if presel == 'll':
                    if kinematics:
                        #pass_nIsoLeptons = np.array(rf['eventTree']['nIsoLeptons'].array()) == 2

                        lepTypes = rf['lepTypes'].array()
                        
                        pass_ltype11 = np.sum(np.abs(lepTypes) == 11, axis=1) == 2
                        pass_ltype13 = np.sum(np.abs(lepTypes) == 13, axis=1) == 2
                        
                        chunk['ll_dilepton_type'] = pass_ltype11*11 + pass_ltype13*13
                        chunk['ll_mz'] = rf['dileptonMass'].array()
                        
                elif kinematics:
                    chunk['vv_mhh'] = rf['dihiggsMass'].array()
                    
        # TODO: handle kinematics=True
        results[pointer:(pointer+chunk_size)] = chunk
        
        pointer += chunk_size

    return results

def get_final_state_counts(DATA_ROOT:str,
                           branches:Iterable,
                           chunks_f:Optional[np.ndarray]=None):

    fs_columns = ['Nd', 'Nu', 'Ns', 'Nc', 'Nb', 'Nt', 'Ne1', 'Nn1', 'Ne2', 'Nn2', 'Ne3', 'Nv3', 'Ng', 'Ny', 'NZ', 'NW', 'NH']
    dtype = [('branch', ('<U32' if isinstance(branches[0], str) else 'I') if chunks_f is None else chunks_f.dtype['branch']), ('event', 'I')]
    for id in fs_columns:
        dtype.append((id, 'B'))

    res_size = 0 if chunks_f is None else np.sum(chunks_f['chunk_size_factual'][np.isin(chunks_f['branch'], branches)])
    fs_counts = np.zeros(res_size, dtype=dtype)
    
    pointer = 0
    
    for branch in tqdm(branches):
        with ur.open(f'{DATA_ROOT}/{branch}_FinalStates.root:eventTree') as a:
            chunk_size = len(a['event'].array())

            chunk = np.zeros(chunk_size, dtype=dtype)
            chunk['branch'] = branch
            chunk['event'] = a['event'].array()
            fs_counts_raw = a['final_state_counts'][1].array()
            
            for i in range(len(fs_columns)):
                chunk[fs_columns[i]] = fs_counts_raw[:, i] 
        
        if chunks_f is None:
            fs_counts = np.concatenate([fs_counts, chunk])
        else:
            fs_counts[pointer:(pointer+chunk_size)] = chunk
            pointer += chunk_size
                
    return fs_counts

def calc_preselection_by_event_categories(presel_results:np.ndarray, processes:np.ndarray, weights:np.ndarray, category_map_inv:dict,
                                          hypothesis:str, weighted:bool, quantity:str, event_categories:Optional[list[int]]=[11, 16, 12, 13, 14], additional_event_categories:Optional[int]=3,
                                        xlim:Optional[tuple]=None, check_pass:bool=False)->Iterable[dict]:
    
    """Calculate the preselection results for a given hypothesis by event categories

    Args:
        presel_results (np.ndarray): _description_
        weights (np.ndarray): _description_
        hypothesis (str): _description_
        event_categories (list, optional): _description_. Defaults to [17].
        additional_event_categories (Optional[int], optional): _description_. Defaults to 3.
        quantity (str, optional): _description_. Defaults to 'll_mz'.
        unit (str, optional): _description_. Defaults to 'GeV'.
        nbins (int, optional): _description_. Defaults to 100.
        xlim (Optional[tuple], optional): _description_. Defaults to None.
        check_pass (bool, optional): _description_. Defaults to False.
        yscale (Optional[str], optional): _description_. Defaults to None.
        ild_style_kwargs (dict, optional): _description_. Defaults to {}.

    Returns:
        _type_: _description_
    """
    
    hypothesis_key = hypothesis[:2]
    
    if xlim is None:
        subset = presel_results
    else:
        subset = presel_results[(presel_results[quantity] > xlim[0]) & (presel_results[quantity] < xlim[1])]
    
    # Find relevant event categories
    if weighted:
        categories = np.unique(subset['event_category'])
        counts = np.zeros(len(categories), dtype=float)
        for i, cat in enumerate(categories):
            counts[i] += weights['weight'][subset['pid'][subset['event_category'] == cat]].sum()
        
    else:
        categories, counts = np.unique(subset['event_category'], return_counts=True)
        
    count_sort_ind = np.argsort(-counts)
    categories = categories[count_sort_ind]
    
    mask = np.isin(categories, event_categories) if event_categories is not None else np.zeros(len(categories), dtype='?')
    
    if additional_event_categories is not None:
        n_additional = 0
        for i in range(len(categories)):
            if not mask[i]:
                if n_additional < additional_event_categories:
                    mask[i] = True
                    n_additional += 1
                else:
                    break
                
    categories = categories[mask]
    
    calc_dict_all  = {}
    calc_dict_pass = {}
    
    for category in (pbar := tqdm(categories)):
        label = category_map_inv[category]
        pbar.set_description(f'Processing event category {label}')
        
        covered_processes = []

        mask = (subset['event_category'] == category)
        pids = np.unique(subset['pid'][mask])
        
        process_masks  = []
        
        # Collect contributions from all proc_pol combinations of a process
        for pid in pids:
            process_name = processes['process'][processes['pid'] == pid][0]
            
            if process_name in covered_processes:
                continue
            else:
                covered_processes.append(process_name)
            
            mask_process = np.zeros(len(mask), dtype='?')
            
            for pidc in processes['pid'][processes['process'] == process_name]:
                #print(f"> {processes['proc_pol'][processes['pid'] == pidc][0]}")
                mask_process = mask_process | (subset['pid'] == pidc)
            
            # Use that indices of weights = weights['pid']
            mask_process = mask & mask_process
            
            process_masks.append(mask_process)
        
        category_mask = np.logical_or.reduce(process_masks)
        
        calc_dict_all[label] = (subset[quantity][category_mask], weights['weight'][subset['pid'][category_mask]])
        
        if check_pass:
            category_mask_pass = category_mask & subset[f'{hypothesis_key}_pass']
            calc_dict_pass[label] = (subset[quantity][category_mask_pass], weights['weight'][subset['pid'][category_mask_pass]])
            
    if check_pass:
        return [calc_dict_all, calc_dict_pass]
    else:
        return [calc_dict_all]    