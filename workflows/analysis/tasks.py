# coding: utf-8

import law.util
from zhh import get_raw_files
import law
from law.util import flatten
import luigi

# import our "framework" tasks
from analysis.framework import HTCondorWorkflow
from zhh import plot_preselection_pass, is_readable, ProcessIndex, get_adjusted_time_per_event, get_runtime_analysis, get_sample_chunk_splits, get_process_normalization
from phc import export_figures, ShellTask, BaseTask, ForcibleTask

from typing import Optional, Union
import numpy as np
import uproot as ur
import os.path as osp
        
class PreselectionAbstract(ShellTask, HTCondorWorkflow, law.LocalWorkflow):
    debug = True
    
    def workflow_requires(self):
        reqs = super().workflow_requires()
        reqs['raw_index'] = CreateRawIndex.req(self)
        
        if not self.debug:
            reqs['preselection_chunks'] = CreatePreselectionChunks.req(self)
        
        return reqs
    
    @law.dynamic_workflow_condition
    def workflow_condition(self):
        # declare that the branch map can be built only if the workflow requirement exists
        # the decorator will trigger a run of workflow_requires beforehand
        if len(self.input()) > 0:
            # here: self.input() refers to the outputs of tasks defined in workflow_requires()
            return all(elem.exists() for elem in flatten(self.input()))
            #return self.input()["raw_index"][0].exists() and self.input()["raw_index"][1].exists()
        else:
            return True
    
    @workflow_condition.create_branch_map
    def create_branch_map(self) -> Union[
        dict[int, str],
        dict[int, tuple[str, int, int]]
        ]:
        samples = np.load(self.input()['raw_index'][1].path)
        
        if 'preselection_chunks' in self.input():
            scs = np.load(self.input()['preselection_chunks'].path)
            res = { k: v for k, v in zip(scs['branch'].tolist(), zip(scs['location'], scs['chunk_start'], scs['chunk_size']))}
                
        else: 
            # arr = get_raw_files(debug=self.debug)
            # arr = list(filter(is_readable, arr))
            # res = { k: v for k, v in zip(list(range(len(arr))), arr) }
            
            selection = samples[np.lexsort((samples['location'], samples['proc_pol']))]
            
            arr = []
            for proc_pol in np.unique(selection['proc_pol']):
                arr.append(selection[np.where(selection['proc_pol'] == proc_pol)[0][0]]['location'])

            # arr = list(samples['location'])
                
            res = { k: v for k, v in zip(list(range(len(arr))), arr) }
        
        return res

    @workflow_condition.output
    def output(self):
        return [
            self.local_target(f'{self.branch}_PreSelection_llHH.root'),
            self.local_target(f'{self.branch}_PreSelection_vvHH.root'),
            self.local_target(f'{self.branch}_PreSelection_qqHH.root'),
            self.local_target(f'{self.branch}_FinalStates.root'),
            self.local_target(f'{self.branch}_FinalStateMeta.json'),
            self.local_target(f'{self.branch}_Source.txt')
        ]

    def build_command(self, fallback_level):
        temp_files = self.output()
        src = self.branch_map[self.branch]
        
        if isinstance(src, tuple):
            src_file = src[0]
            n_events_skip = src[1]
            n_events_max = src[2]
        else:
            src_file = str(src)
            n_events_skip = 0
            n_events_max = 50 if self.debug else 0
        
        # Check if sample belongs to new or old MC production to change MCParticleCollectionName
        mcp_col_name = 'MCParticlesSkimmed' if '/hh/' in src_file else 'MCParticle'
        
        cmd =  f'source $REPO_ROOT/setup.sh'
        cmd += f' && echo "Starting Marlin at $(date)"'
        
        src_txt_target = self.local_path(str(self.branch) + "_Source.txt")
        root_files = ['PreSelection_llHH.root', 'PreSelection_vvHH.root', 'PreSelection_qqHH.root', 'FinalStates.root']
        for suffix in ['FinalStateMeta.json'] + root_files:
            target_path = self.local_path(str(self.branch) + "_" + suffix)
            cmd += f' && (if [[ ! -f {src_txt_target} && -f {target_path} ]]; then rm {target_path}; fi)' # should not be necessary as we're writing to a temp file anyway
        
        cmd += f' && ( Marlin $REPO_ROOT/scripts/ZHH_v2.xml --global.MaxRecordNumber={str(n_events_max)} --global.LCIOInputFiles={src_file} --global.SkipNEvents={str(n_events_skip)} --constant.OutputDirectory=. --constant.MCParticleCollectionName={mcp_col_name} || true )'
        cmd += f' && echo "Finished Marlin at $(date)"'
        
        # is_root_readable (necessary because CheatedMCOverlayRemoval crashes Marlin before it can properly exit, see above)
        for suffix in root_files:
            cmd += f' && is_root_readable ./zhh_{suffix}'
        
        cmd += f' && mv zhh_PreSelection_llHH.root {temp_files[0].path}'
        cmd += f' && mv zhh_PreSelection_vvHH.root {temp_files[1].path}'
        cmd += f' && mv zhh_PreSelection_qqHH.root {temp_files[2].path}'
        cmd += f' && mv zhh_FinalStates.root {temp_files[3].path}'
        cmd += f' && mv zhh_FinalStateMeta.json {temp_files[4].path}'
        cmd += f' && echo "{self.branch_map[self.branch]}" >> {temp_files[5].path}'

        return cmd
    
class PreselectionRuntime(PreselectionAbstract):
    """Generates a runtime analysis for each proc_pol combination, essentially by running in debug mode

    Args:
        PreselectionAbstract (_type_): _description_
    """
    debug = True

class PreselectionFinal(PreselectionAbstract):
    debug = False # luigi.BoolParameter(default=False)

class CreatePreselectionChunks(BaseTask):
    mode = luigi.IntParameter(default=1)
    # 0 -> get_adjusted_time_per_event(True, 4, 2)
    # 1 -> get_process_normalization(GAIN=46) with get_adjusted_time_per_event(True)
    
    def requires(self):
        return [
            CreateRawIndex.req(self),
            PreselectionRuntime.req(self)
        ]

    def output(self):
        return self.local_target('chunks.npy')
    
    def run(self):
        SAMPLE_INDEX = self.input()[0][1].path
        DATA_ROOT = osp.dirname(self.input()[1]['collection'][0][0].path)
        
        processes = np.load(self.input()[0][0].path)
        samples = np.load(SAMPLE_INDEX)
        
        if self.mode == 0:
            runtime_analysis = get_runtime_analysis(DATA_ROOT)
            atp = get_adjusted_time_per_event(runtime_analysis, True, 4, 2)
            chunk_splits = get_sample_chunk_splits(samples, adjusted_time_per_event=atp)
        elif self.mode == 1:
            pn = get_process_normalization(processes, samples, GAIN=46)
            atp = get_adjusted_time_per_event(runtime_analysis, True)
            
            chunk_splits = get_sample_chunk_splits(samples, process_normalization=pn, adjusted_time_per_event=atp)
        else:
            raise Exception(f'Mode {str(self.mode)} not implemented')
        
        self.output().parent.touch()
        np.save(self.output().path, chunk_splits)
        
        self.publish_message(f'Compiled preselection chunks')

class CreateRawIndex(BaseTask):
    """
    This task creates two indeces: An index of available SLCIO sample files with information about the file location, number of events, physics process and polarization + an index containing all encountered physics processes for each polarization and their cross section-section values 
    """
    index: Optional[np.ndarray]
    
    def output(self):
        return [
            self.local_target('processes.npy'),
            self.local_target('samples.npy')
        ]
    
    def run(self):
        temp_files = self.output()
        
        temp_files[0].parent.touch()
        self.index = index = ProcessIndex(temp_files[0], temp_files[1], get_raw_files())
        self.index.load()
        
        self.publish_message(f'Loaded {len(index.samples)} samples and {len(index.processes)} processes')

class CreatePlots(BaseTask):
    """
    This task requires the Preselection workflow and extracts the created data to create plots.
    """

    def requires(self):
        return PreselectionFinal.req(self)

    def output(self):
        # output a plain text file
        return self.local_target("plots.pdf")

    def run(self):
        # Get targets of dependendies and get the file paths of relevant files 
        inputs = self.input()['collection'].targets
        
        files = []
        for input in flatten(inputs):
            if input.path.endswith('PreSelection.root'):
                files.append(input.path)
                
        # Extract columns using uproot
        vecs = []
        for f in files:
            d = ur.open(f)['eventTree']
            vecs.append(np.array(d['preselsPassedVec'].array()))
            
        vecs = np.concatenate(vecs)
        vecs[vecs < 0] = 0 # setting invalid entries to 0
        
        # Create the plots and save them to
        figs = plot_preselection_pass(vecs)
        
        self.output().parent.touch() # Create intermediate directories and save plots    
        export_figures(self.output().path, figs)
        
        # Status message
        self.publish_message(f'exported {len(figs)} plots to {self.output().path}')


