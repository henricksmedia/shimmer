import sys
sys.path.insert(0, 'D:/MusicVault/Tools/Shimmer')
for m in ('shimmer.server', 'shimmer.pipeline', 'shimmer.engine',
          'shimmer.mastering', 'shimmer.cli', 'shimmer.audio_io',
          'shimmer.chain', 'shimmer.detect', 'shimmer.__main__'):
    __import__(m)
hits = sorted(k for k in sys.modules if 'budget' in k or 'perceptual' in k)
print('after importing every pipeline entry point, budget/perceptual in sys.modules:', hits)
